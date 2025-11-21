# ============================================================================
# CLAUDE CONTEXT - PLATFORM MODELS (API REQUESTS & ORCHESTRATION)
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Core Models - Platform API request and orchestration database schema definitions
# PURPOSE: Pydantic models for Platform layer - SINGLE SOURCE OF TRUTH for database schema
# LAST_REVIEWED: 1 NOV 2025
# EXPORTS: ApiRequest, OrchestrationJob, PlatformRequestStatus, DataType, OperationType, PlatformRequest
# INTERFACES: BaseModel (Pydantic)
# PYDANTIC_MODELS: All models in this file define database schema via Infrastructure-as-Code
# DEPENDENCIES: pydantic, typing, datetime, enum
# SOURCE: These models ARE the schema - database DDL auto-generated from field definitions
# SCOPE: Platform layer data model - orchestration above CoreMachine
# VALIDATION: Pydantic field validation + PostgreSQL constraints (auto-generated)
# PATTERNS: Infrastructure-as-Code (schema from code), Data Transfer Object (DTO)
# ENTRY_POINTS: from core.models.platform import ApiRequest, OrchestrationJob
# INDEX:
#   - Enums: Line 48
#   - PlatformRequest (DTO): Line 62
#   - ApiRequest (DB): Line 85
#   - OrchestrationJob (DB): Line 140
# ============================================================================

"""
Platform Layer Data Models - Infrastructure-as-Code Pattern

This module defines the Platform layer data models using Pydantic.
These models are the SINGLE SOURCE OF TRUTH for the database schema.

Architecture Pattern (Same as JobRecord/TaskRecord):
    1. Define Pydantic models with Field constraints (max_length, etc.)
    2. PydanticToSQL introspects models and generates PostgreSQL DDL
    3. Schema deployment uses generated DDL (no manual schema definition)
    4. Result: Zero drift between Python models and database schema

Database Tables Auto-Generated:
    - app.api_requests (from ApiRequest)
    - app.orchestration_jobs (from OrchestrationJob)

Table Names (29 OCT 2025):
    - "api_requests": Client-facing layer - RESTful API requests from DDH
    - "orchestration_jobs": Execution layer - Maps API requests to CoreMachine jobs

"""

from pydantic import BaseModel, Field, field_validator
from typing import Dict, Any, List, Optional, Union
from datetime import datetime
from enum import Enum
import re


# ============================================================================
# ENUMS - Auto-converted to PostgreSQL ENUM types
# ============================================================================

class PlatformRequestStatus(str, Enum):
    """
    Platform request status enum.

    Auto-generates: CREATE TYPE app.platform_request_status_enum AS ENUM (...)
    """
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class DataType(str, Enum):
    """
    Supported data types for processing.

    Auto-generates: CREATE TYPE app.data_type_enum AS ENUM (...)
    """
    RASTER = "raster"
    VECTOR = "vector"
    POINTCLOUD = "pointcloud"
    MESH_3D = "mesh_3d"
    TABULAR = "tabular"


class OperationType(str, Enum):
    """
    DDH operation types.

    Auto-generates: CREATE TYPE app.operation_type_enum AS ENUM (...)

    Added: 1 NOV 2025 - DDH APIM integration
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
    Accepts DDH API v1 format and transforms to internal ApiRequest format.

    Updated: 1 NOV 2025 - DDH APIM integration
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
    operation: OperationType = Field(..., description="Operation type: CREATE/UPDATE/DELETE")

    # ========================================================================
    # DDH File Information (Required)
    # ========================================================================
    container_name: str = Field(..., max_length=100, description="Azure storage container name (e.g., bronze-vectors)")
    file_name: Union[str, List[str]] = Field(..., description="File name(s) - single string or array for raster collections")

    # ========================================================================
    # DDH Service Metadata (Required)
    # ========================================================================
    service_name: str = Field(..., max_length=255, description="Human-readable service name (maps to STAC item_id)")
    access_level: str = Field(..., max_length=50, description="Data classification: public, OUO, restricted")

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
        description="""
        Processing options from DDH.

        Vector Options:
        - overwrite: bool (replace existing service)
        - lon_column: str (CSV longitude column)
        - lat_column: str (CSV latitude column)
        - wkt_column: str (WKT geometry column)
        - time_index: str | array (temporal indexing - Phase 2)
        - attribute_index: str | array (attribute indexing - Phase 2)

        Raster Options:
        - crs: int (EPSG code)
        - nodata_value: int (NoData value)
        - band_descriptions: dict (band metadata - Phase 2)
        - raster_collection: str (collection name - Phase 2)
        - temporal_order: dict (time-series mapping - Phase 2)

        Styling Options (Phase 2):
        - type: str (unique/classed/stretch)
        - property: str (attribute for visualization)
        - color_ramp: str | array (color palette)
        - classification: str (natural-breaks/quantile/equal/standard-deviation)
        - classes: int (number of classes)
        """
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
        if ext in ['geojson', 'gpkg', 'shp', 'zip', 'csv']:
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
        """
        item_id = self.service_name.lower()
        item_id = item_id.replace(' ', '-')
        item_id = re.sub(r'[^a-z0-9\-_]', '', item_id)
        return item_id

    # ========================================================================
    # Validators
    # ========================================================================

    @field_validator('container_name')
    @classmethod
    def validate_container(cls, v: str) -> str:
        """Ensure container name follows naming convention"""
        valid_containers = [
            'bronze-vectors', 'bronze-rasters', 'bronze-misc', 'bronze-temp',
            'silver-cogs', 'silver-vectors', 'silver-mosaicjson', 'silver-stac-assets'
        ]
        if v not in valid_containers:
            raise ValueError(f"Container must be one of: {', '.join(valid_containers)}")
        return v

    @field_validator('access_level')
    @classmethod
    def validate_access_level(cls, v: str) -> str:
        """Ensure access level is valid"""
        valid_levels = ['public', 'OUO', 'restricted']
        if v not in valid_levels:
            raise ValueError(f"access_level must be one of: {', '.join(valid_levels)}")
        return v


# ============================================================================
# DATABASE MODELS - Infrastructure-as-Code Schema Definitions
# ============================================================================

class ApiRequest(BaseModel):
    """
    API request database record (client-facing layer).

    ⚠️ CRITICAL: This model IS the database schema definition.
    The PostgreSQL table schema is auto-generated from these field definitions.

    This table represents client-facing API requests from DDH.
    Each request can orchestrate multiple CoreMachine jobs (tracked via OrchestrationJob table).

    Schema Generation:
    - Field type → PostgreSQL type (str → VARCHAR, Dict → JSONB, etc.)
    - max_length → VARCHAR(n)
    - default → DEFAULT value
    - Optional → NULL, required → NOT NULL
    - Enum → ENUM type + constraint

    Auto-generates:
        CREATE TABLE app.api_requests (
            request_id VARCHAR(32) PRIMARY KEY,
            dataset_id VARCHAR(255) NOT NULL,
            resource_id VARCHAR(255) NOT NULL,
            version_id VARCHAR(50) NOT NULL,
            data_type VARCHAR(50) NOT NULL,
            status app.platform_request_status_enum DEFAULT 'pending',
            jobs JSONB DEFAULT '{}'::jsonb,
            parameters JSONB DEFAULT '{}'::jsonb,
            metadata JSONB DEFAULT '{}'::jsonb,
            result_data JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );

    Follows same Infrastructure-as-Code pattern as JobRecord (core/models/job.py).
    """
    request_id: str = Field(
        ...,
        max_length=32,
        description="SHA256 hash of dataset+resource+version IDs (first 32 chars)"
    )
    dataset_id: str = Field(..., max_length=255, description="DDH dataset identifier")
    resource_id: str = Field(..., max_length=255, description="DDH resource identifier")
    version_id: str = Field(..., max_length=50, description="DDH version identifier")
    data_type: str = Field(..., max_length=50, description="Type of data being processed")
    status: PlatformRequestStatus = Field(
        default=PlatformRequestStatus.PENDING,
        description="Current status of platform request"
    )
    jobs: Dict[str, Any] = Field(
        default_factory=dict,
        description="""
        CoreMachine jobs orchestrated for this request.

        Structure:
        {
            "validate_raster": {
                "job_id": "abc123...",
                "job_type": "validate_raster",
                "status": "completed",
                "sequence": 1,
                "created_at": "2025-10-29T12:00:00Z",
                "completed_at": "2025-10-29T12:01:30Z"
            },
            "create_cog": {
                "job_id": "def456...",
                "job_type": "process_raster",
                "status": "processing",
                "sequence": 2,
                "created_at": "2025-10-29T12:01:31Z",
                "depends_on": ["validate_raster"]
            }
        }

        Key = logical step name (human-readable)
        Value = job metadata with job_id reference
        """
    )
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Processing parameters from original request"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="""
        Additional metadata about the request.

        DDH Metadata Fields (added 1 NOV 2025):
        - service_name: str (human-readable service name, maps to STAC title)
        - stac_item_id: str (URL-safe STAC item identifier)
        - access_level: str (public/OUO/restricted - enforcement Phase 2)
        - description: str (service description for API/STAC)
        - tags: list (categorization/search tags)
        - client_id: str (client application identifier)
        - source_location: str (Azure blob URL)
        - submission_time: str (ISO 8601 timestamp)
        """
    )
    result_data: Optional[Dict[str, Any]] = Field(
        None,
        description="Final results after all jobs complete"
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp when request was created"
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp when request was last updated"
    )

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for database storage.

        Note: This method will be less necessary once repository uses
        Pydantic model_dump() directly, but kept for backward compatibility.
        """
        return {
            'request_id': self.request_id,
            'dataset_id': self.dataset_id,
            'resource_id': self.resource_id,
            'version_id': self.version_id,
            'data_type': self.data_type,
            'status': self.status.value if isinstance(self.status, Enum) else self.status,
            'job_ids': self.job_ids,
            'parameters': self.parameters,
            'metadata': self.metadata,
            'result_data': self.result_data,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class OrchestrationJob(BaseModel):
    """
    Orchestration job mapping (execution layer).

    ⚠️ CRITICAL: This model IS the database schema definition.
    The PostgreSQL table schema is auto-generated from these field definitions.

    This table maps API requests to CoreMachine jobs, enabling:
    - Bidirectional queries (request → jobs, job → requests)
    - Workflow orchestration tracking
    - Multiple requests referencing same job (idempotency)

    Auto-generates:
        CREATE TABLE app.orchestration_jobs (
            request_id VARCHAR(32) NOT NULL,
            job_id VARCHAR(64) NOT NULL,
            job_type VARCHAR(100) NOT NULL,
            sequence INTEGER DEFAULT 1,
            status VARCHAR(20) DEFAULT 'pending',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (request_id, job_id),
            FOREIGN KEY (request_id) REFERENCES app.api_requests(request_id) ON DELETE CASCADE
        );

    This table tracks:
    - Which CoreMachine jobs belong to which API request
    - The sequence/order of jobs in the request workflow
    - Individual job status (independent of API request status)
    """
    request_id: str = Field(
        ...,
        max_length=32,
        description="API request ID (foreign key to api_requests)"
    )
    job_id: str = Field(
        ...,
        max_length=64,
        description="CoreMachine job ID (SHA256 hash)"
    )
    job_type: str = Field(
        ...,
        max_length=100,
        description="Type of CoreMachine job (e.g., 'process_raster')"
    )
    sequence: int = Field(
        default=1,
        description="Order of this job in the request workflow"
    )
    status: str = Field(
        default="pending",
        max_length=20,
        description="Job status (mirrors CoreMachine job status)"
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp when mapping was created"
    )


# ============================================================================
# SCHEMA METADATA - Used by PydanticToSQL generator
# ============================================================================

# Table names (29 OCT 2025 - Renamed for API clarity)
# - "api_requests": Client-facing layer (what user asked for)
# - "orchestration_jobs": Execution layer (how we execute it)
PLATFORM_TABLE_NAMES = {
    'ApiRequest': 'api_requests',
    'OrchestrationJob': 'orchestration_jobs'
}

# Primary keys (auto-detected, but explicit is better)
PLATFORM_PRIMARY_KEYS = {
    'ApiRequest': ['request_id'],
    'OrchestrationJob': ['request_id', 'job_id']  # Composite key
}

# Indexes to create (in addition to primary key indexes)
PLATFORM_INDEXES = {
    'ApiRequest': [
        ('status',),           # Single column index
        ('dataset_id',),       # Single column index
        ('created_at',),       # Single column index (DESC handled in generator)
    ]
}
