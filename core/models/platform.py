# ============================================================================
# CLAUDE CONTEXT - PLATFORM MODELS (API REQUESTS & ORCHESTRATION)
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Core Models - Platform API request and orchestration database schema definitions
# PURPOSE: Pydantic models for Platform layer - SINGLE SOURCE OF TRUTH for database schema
# LAST_REVIEWED: 29 OCT 2025
# EXPORTS: ApiRequest, OrchestrationJob, PlatformRequestStatus, DataType, PlatformRequest
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

Author: Robert and Geospatial Claude Legion
Date: 29 OCT 2025 - Migrated to Infrastructure-as-Code pattern
"""

from pydantic import BaseModel, Field, field_validator
from typing import Dict, Any, List, Optional
from datetime import datetime
from enum import Enum


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


# ============================================================================
# DATA TRANSFER OBJECTS (DTOs) - Not stored in database
# ============================================================================

class PlatformRequest(BaseModel):
    """
    Platform request from external application (DDH).

    This is a DTO (Data Transfer Object) for incoming HTTP requests.
    NOT stored directly in database - converted to ApiRequest for persistence.

    DDH Integration:
    - dataset_id: DDH dataset identifier (mandatory)
    - resource_id: DDH resource identifier (mandatory)
    - version_id: DDH version identifier (mandatory)
    """
    dataset_id: str = Field(..., description="DDH dataset identifier")
    resource_id: str = Field(..., description="DDH resource identifier")
    version_id: str = Field(..., description="DDH version identifier")
    data_type: DataType = Field(..., description="Type of data to process")
    source_location: str = Field(..., description="Azure blob URL or path")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Processing parameters")
    client_id: str = Field(..., description="Client application identifier (e.g., 'ddh')")

    @field_validator('source_location')
    @classmethod
    def validate_source(cls, v: str) -> str:
        """Ensure source is Azure blob storage"""
        if not (v.startswith('https://') or v.startswith('wasbs://') or v.startswith('/')):
            raise ValueError("Source must be Azure blob URL or absolute path")
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
        description="Additional metadata about the request"
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
