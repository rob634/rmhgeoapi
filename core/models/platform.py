"""
Platform Layer Data Models - Thin Tracking Pattern.

Platform is an Anti-Corruption Layer (ACL) that translates DDH API to CoreMachine.
Uses thin tracking with 1:1 mapping: api_requests → job_id.

Architecture:
    - Platform translates DDH params → CoreMachine params
    - Creates ONE CoreMachine job per request
    - Stores request_id → job_id for DDH status lookups
    - No orchestration - CoreMachine handles job internals

Request ID Generation:
    SHA256(dataset_id + resource_id + version_id)[:32]
    Idempotent: same inputs = same ID

Exports:
    ApiRequest: Database model for request tracking
    PlatformRequest: DTO for incoming requests
    PlatformRequestStatus, DataType, OperationType: Enums
    - Natural deduplication of resubmitted requests

Database Tables Auto-Generated (stored in app schema with jobs/tasks):
    - app.api_requests (thin: request_id, DDH IDs, job_id, created_at)
    - NOTE: Platform tables live in app schema (not a separate platform schema)
    - This ensures api_requests is cleared during full-rebuild with other app tables

Removed (22 NOV 2025):
    - app.orchestration_jobs table (no job chaining)
    - OrchestrationJob model (moved to history)
    - jobs JSONB column (1:1 mapping now via job_id)
    - status column (delegate to CoreMachine)
    - metadata column (pass through, don't store twice)
"""

from pydantic import BaseModel, Field, field_validator
from typing import Dict, Any, List, Optional, Union
from datetime import datetime
from enum import Enum
import re


# ============================================================================
# ENUMS
# ============================================================================

class PlatformRequestStatus(str, Enum):
    """
    Platform request status enum.

    Note: With thin tracking, we mostly delegate status to CoreMachine.
    This enum is kept for backward compatibility and API responses.
    """
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class DataType(str, Enum):
    """
    Supported data types for processing.

    Used to determine which CoreMachine job to create.
    """
    RASTER = "raster"
    VECTOR = "vector"
    POINTCLOUD = "pointcloud"
    MESH_3D = "mesh_3d"
    TABULAR = "tabular"


class OperationType(str, Enum):
    """
    DDH operation types.

    CREATE is primary. UPDATE/DELETE are Phase 2.
    """
    CREATE = "CREATE"
    UPDATE = "UPDATE"  # Phase 2
    DELETE = "DELETE"  # Phase 2


# ============================================================================
# DATA TRANSFER OBJECTS (DTOs) - Not stored in database
# ============================================================================

class PlatformRequest(BaseModel):
    """
    Platform request from external application (DDH).

    This is a DTO (Data Transfer Object) for incoming HTTP requests.
    Accepts DDH API v1 format and gets translated to CoreMachine job parameters.

    The Platform layer validates this DTO, then uses PlatformConfig to:
    - Generate output naming (table names, folder paths, STAC IDs)
    - Validate container names and access levels
    - Create deterministic request_id from DDH identifiers

    Updated: 22 NOV 2025 - Simplified validation, delegate to PlatformConfig
    """

    # ========================================================================
    # DDH Core Identifiers (Required)
    # ========================================================================
    dataset_id: str = Field(..., max_length=255, description="DDH dataset identifier")
    resource_id: str = Field(..., max_length=255, description="DDH resource identifier")
    version_id: str = Field(..., max_length=50, description="DDH version identifier")

    # ========================================================================
    # DDH Operation (Required)
    # ========================================================================
    operation: OperationType = Field(
        default=OperationType.CREATE,
        description="Operation type: CREATE/UPDATE/DELETE"
    )

    # ========================================================================
    # DDH File Information (Required)
    # ========================================================================
    container_name: str = Field(
        ...,
        max_length=100,
        description="Azure storage container name (e.g., bronze-vectors)"
    )
    file_name: Union[str, List[str]] = Field(
        ...,
        description="File name(s) - single string or array for raster collections"
    )

    # ========================================================================
    # DDH Service Metadata (Required)
    # ========================================================================
    service_name: str = Field(
        ...,
        max_length=255,
        description="Human-readable service name (maps to STAC item_id)"
    )
    access_level: str = Field(
        default="OUO",
        max_length=50,
        description="Data classification: public, OUO, restricted"
    )

    # ========================================================================
    # DDH Optional Metadata
    # ========================================================================
    description: Optional[str] = Field(None, description="Service description for API/STAC metadata")
    tags: List[str] = Field(default_factory=list, description="Tags for categorization/search")

    # ========================================================================
    # DDH Processing Options (Optional)
    # ========================================================================
    processing_options: Dict[str, Any] = Field(
        default_factory=dict,
        description="Processing options (crs, nodata_value, overwrite, etc.)"
    )

    # ========================================================================
    # Client Identifier
    # ========================================================================
    client_id: str = Field(default="ddh", description="Client application identifier")

    # ========================================================================
    # Computed Properties
    # ========================================================================

    @property
    def source_location(self) -> str:
        """
        Construct Azure blob storage URL from container_name + file_name.

        Returns:
            Full Azure blob URL for the first file (if array) or single file
        """
        base_url = "https://rmhazuregeo.blob.core.windows.net"

        # Handle array of file names (raster collections)
        if isinstance(self.file_name, list):
            first_file = self.file_name[0]
            return f"{base_url}/{self.container_name}/{first_file}"

        # Handle single file name
        return f"{base_url}/{self.container_name}/{self.file_name}"

    @property
    def data_type(self) -> DataType:
        """
        Detect data type from file extension.

        Returns:
            DataType enum (RASTER, VECTOR, POINTCLOUD, MESH_3D, TABULAR)
        """
        # Get first file name if array
        file_name = self.file_name[0] if isinstance(self.file_name, list) else self.file_name

        # Extract extension
        ext = file_name.lower().split('.')[-1]

        # Map extension to data type
        if ext in ['geojson', 'gpkg', 'shp', 'zip', 'csv', 'gdb', 'kml', 'kmz']:
            return DataType.VECTOR
        elif ext in ['tif', 'tiff', 'img', 'hdf', 'nc']:
            return DataType.RASTER
        elif ext in ['las', 'laz', 'e57']:
            return DataType.POINTCLOUD
        elif ext in ['obj', 'fbx', 'gltf', 'glb']:
            return DataType.MESH_3D
        elif ext in ['xlsx', 'parquet']:
            return DataType.TABULAR
        else:
            raise ValueError(f"Unsupported file format: {ext}")

    @property
    def stac_item_id(self) -> str:
        """
        Generate URL-safe STAC item_id from service_name.

        Example: "King County Parcels 2024" → "king-county-parcels-2024"

        Note: Consider using PlatformConfig.generate_stac_item_id() for consistency.
        """
        item_id = self.service_name.lower()
        item_id = item_id.replace(' ', '-')
        item_id = re.sub(r'[^a-z0-9\-_]', '', item_id)
        return item_id

    @property
    def is_raster_collection(self) -> bool:
        """Check if this is a raster collection request (multiple files)."""
        return (
            isinstance(self.file_name, list) and
            len(self.file_name) > 1 and
            self.data_type == DataType.RASTER
        )


# ============================================================================
# DATABASE MODELS - Thin Tracking (22 NOV 2025)
# ============================================================================

class ApiRequest(BaseModel):
    """
    API request database record - THIN TRACKING ONLY.

    ⚠️ SIMPLIFIED (22 NOV 2025): This is now a thin tracking layer.

    Purpose:
        - Store DDH identifiers for status lookup
        - Map request_id → job_id (1:1)
        - Enable DDH to poll /api/platform/status/{request_id}
        - Platform looks up job_id, fetches status from CoreMachine

    What's REMOVED:
        - jobs JSONB (was: multi-job tracking)
        - status column (delegate to CoreMachine job status)
        - parameters JSONB (passed to CoreMachine, not stored twice)
        - metadata JSONB (passed to CoreMachine, not stored twice)
        - result_data JSONB (CoreMachine stores results)
        - updated_at (thin record, doesn't update)

    Auto-generates:
        CREATE TABLE app.api_requests (
            request_id VARCHAR(32) PRIMARY KEY,
            dataset_id VARCHAR(255) NOT NULL,
            resource_id VARCHAR(255) NOT NULL,
            version_id VARCHAR(50) NOT NULL,
            job_id VARCHAR(64) NOT NULL,
            data_type VARCHAR(50) NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );

    Request ID Generation:
        SHA256(dataset_id | resource_id | version_id)[:32]
        - Idempotent: same DDH identifiers = same request_id
        - See config.generate_platform_request_id()
    """
    request_id: str = Field(
        ...,
        max_length=32,
        description="SHA256(dataset_id|resource_id|version_id)[:32] - idempotent"
    )
    dataset_id: str = Field(..., max_length=255, description="DDH dataset identifier")
    resource_id: str = Field(..., max_length=255, description="DDH resource identifier")
    version_id: str = Field(..., max_length=50, description="DDH version identifier")
    job_id: str = Field(
        ...,
        max_length=64,
        description="CoreMachine job ID (1:1 mapping)"
    )
    data_type: str = Field(..., max_length=50, description="Type of data: raster, vector, etc.")
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp when request was created"
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database storage."""
        return {
            'request_id': self.request_id,
            'dataset_id': self.dataset_id,
            'resource_id': self.resource_id,
            'version_id': self.version_id,
            'job_id': self.job_id,
            'data_type': self.data_type,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


# ============================================================================
# SCHEMA METADATA - Used by PydanticToSQL generator
# ============================================================================

# Table names (22 NOV 2025 - Simplified to single table)
PLATFORM_TABLE_NAMES = {
    'ApiRequest': 'api_requests'
    # OrchestrationJob table REMOVED - no job chaining in Platform
}

# Primary keys
PLATFORM_PRIMARY_KEYS = {
    'ApiRequest': ['request_id']
}

# Indexes
PLATFORM_INDEXES = {
    'ApiRequest': [
        ('job_id',),       # Lookup by CoreMachine job
        ('dataset_id',),   # DDH queries by dataset
        ('created_at',),   # Recent requests
    ]
}


# ============================================================================
# BACKWARD COMPATIBILITY - Deprecated exports (22 NOV 2025)
# ============================================================================

# OrchestrationJob is REMOVED - kept as comment for migration reference
# class OrchestrationJob was used for multi-job tracking per request
# This is no longer needed with thin tracking (1:1 request → job mapping)

# If old code imports OrchestrationJob, it will get ImportError
# This is intentional - forces migration to new pattern
