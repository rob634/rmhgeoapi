# ============================================================================
# CLAUDE CONTEXT - ARTIFACT REGISTRY MODELS
# ============================================================================
# STATUS: Core - Internal artifact tracking with client-agnostic UUIDs
# PURPOSE: Track data pipeline outputs with supersession/lineage support
# CREATED: 20 JAN 2026
# LAST_REVIEWED: 21 JAN 2026
# ============================================================================
"""
Artifact Registry Models.

Provides internal artifact tracking independent of client parameter schemes.
Supports overwrite workflows with supersession tracking and revision history.

Key Features:
    - Client-agnostic UUIDs (artifact_id) for internal tracking
    - Flexible client_refs JSONB for any client's parameter schema
    - Supersession chain for overwrite lineage
    - Content hash for duplicate detection

Architecture:
    Platform Layer (DDH, Data360, etc.)
         ↓
    Orchestrator Layer (CoreMachine)
         ↓
    Artifact Layer (this module) - tracks outputs with internal IDs

Exports:
    ArtifactStatus: Lifecycle status enum
    Artifact: Database model for artifact records

Dependencies:
    pydantic: Data validation
    uuid: UUID generation
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional
from uuid import UUID, uuid4
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict, field_serializer


# ============================================================================
# ENUMS
# ============================================================================

class ArtifactStatus(str, Enum):
    """
    Artifact lifecycle status.

    State transitions:
    - PENDING → ACTIVE (artifact creation complete)
    - ACTIVE → SUPERSEDED (replaced by newer version)
    - ACTIVE → ARCHIVED (moved to archive storage)
    - ACTIVE → DELETED (soft deleted)
    - SUPERSEDED → DELETED (cleanup of old versions)
    """
    PENDING = "pending"          # Being created
    ACTIVE = "active"            # Current version
    SUPERSEDED = "superseded"    # Replaced by newer version
    ARCHIVED = "archived"        # Moved to archive storage
    DELETED = "deleted"          # Soft deleted


# ============================================================================
# DATABASE MODELS
# ============================================================================

class Artifact(BaseModel):
    """
    Artifact database model - Internal asset tracking.

    Represents a single output from the data pipeline with:
    - Internal UUID (artifact_id) independent of client params
    - Flexible client_refs JSONB for any client's parameter schema
    - Supersession tracking for overwrite lineage
    - Content hash for duplicate detection

    Design Decisions (20 JAN 2026):
    - STAC Item Handling: Delete old, create new with same ID
    - COG Blob Handling: Overwrite blob in place
    - Revision Numbering: Global monotonic (never resets)
    - Content Hash: Hash output COG after creation
    - Cleanup Timing: Synchronous
    - API Response: artifact_id is INTERNAL ONLY

    Auto-generates:
        CREATE TABLE app.artifacts (
            artifact_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            content_hash VARCHAR(128),
            storage_account VARCHAR(64) NOT NULL,
            container VARCHAR(64) NOT NULL,
            blob_path TEXT NOT NULL,
            size_bytes BIGINT,
            content_type VARCHAR(100),
            blob_version_id VARCHAR(64),
            stac_collection_id VARCHAR(255),
            stac_item_id VARCHAR(255),
            client_type VARCHAR(50) NOT NULL,
            client_refs JSONB NOT NULL,
            source_job_id VARCHAR(64),
            source_task_id VARCHAR(100),
            supersedes UUID REFERENCES app.artifacts(artifact_id),
            superseded_by UUID REFERENCES app.artifacts(artifact_id),
            revision INTEGER NOT NULL DEFAULT 1,
            status app.artifact_status NOT NULL DEFAULT 'active',
            metadata JSONB DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            deleted_at TIMESTAMPTZ
        );
    """

    model_config = ConfigDict()

    @field_serializer('created_at', 'updated_at', 'deleted_at')
    @classmethod
    def serialize_datetime(cls, v: datetime) -> Optional[str]:
        return v.isoformat() if v else None

    @field_serializer('artifact_id', 'supersedes', 'superseded_by')
    @classmethod
    def serialize_uuid(cls, v: UUID) -> Optional[str]:
        return str(v) if v else None

    # ========================================================================
    # INTERNAL IDENTIFIER (Our System's ID - Never Changes)
    # ========================================================================
    artifact_id: UUID = Field(
        default_factory=uuid4,
        description="Internal UUID - our system's identifier, never derived from client params"
    )

    # ========================================================================
    # CONTENT FINGERPRINT (For Deduplication & Integrity)
    # ========================================================================
    content_hash: Optional[str] = Field(
        None,
        max_length=128,
        description="Multihash of output file (STAC file extension v2.1.0 format: 1220 prefix + 64 hex = 68 chars for SHA256)"
    )

    # ========================================================================
    # STORAGE LOCATION (Where the Asset Lives)
    # ========================================================================
    storage_account: str = Field(
        ...,
        max_length=64,
        description="Azure storage account name"
    )
    container: str = Field(
        ...,
        max_length=64,
        description="Blob container name"
    )
    blob_path: str = Field(
        ...,
        description="Path within container"
    )
    size_bytes: Optional[int] = Field(
        None,
        description="File size in bytes"
    )
    content_type: Optional[str] = Field(
        None,
        max_length=100,
        description="MIME type (e.g., 'image/tiff', 'application/geo+json')"
    )
    blob_version_id: Optional[str] = Field(
        None,
        max_length=64,
        description="Azure Blob Storage version ID (if versioning enabled on container)"
    )

    # ========================================================================
    # STAC REFERENCE (Optional - Artifact May Not Have STAC Item)
    # ========================================================================
    stac_collection_id: Optional[str] = Field(
        None,
        max_length=255,
        description="STAC collection ID if cataloged"
    )
    stac_item_id: Optional[str] = Field(
        None,
        max_length=255,
        description="STAC item ID if cataloged"
    )

    # ========================================================================
    # CLIENT REFERENCE MAPPING (Supports ANY Client Schema)
    # ========================================================================
    client_type: str = Field(
        ...,
        max_length=50,
        description="Client identifier (e.g., 'ddh', 'data360', 'manual', 'system')"
    )
    client_refs: Dict[str, Any] = Field(
        ...,
        description="Client-specific reference IDs as JSONB (e.g., DDH dataset_id/resource_id/version_id)"
    )

    # ========================================================================
    # PROCESSING REFERENCE (Link to CoreMachine)
    # ========================================================================
    source_job_id: Optional[str] = Field(
        None,
        max_length=64,
        description="CoreMachine job ID that created this artifact"
    )
    source_task_id: Optional[str] = Field(
        None,
        max_length=100,
        description="CoreMachine task ID that created this artifact"
    )

    # ========================================================================
    # LINEAGE / SUPERSESSION (Track Overwrites)
    # ========================================================================
    supersedes: Optional[UUID] = Field(
        None,
        description="Artifact ID this one replaced (NULL if first version)"
    )
    superseded_by: Optional[UUID] = Field(
        None,
        description="Artifact ID that replaced this one (NULL if current)"
    )
    revision: int = Field(
        default=1,
        ge=1,
        description="Sequential counter - global monotonic per client_refs (never resets)"
    )

    # ========================================================================
    # STATUS (Lifecycle State)
    # ========================================================================
    status: ArtifactStatus = Field(
        default=ArtifactStatus.ACTIVE,
        description="Artifact lifecycle status"
    )

    # ========================================================================
    # METADATA (Flexible Additional Info)
    # ========================================================================
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata (raster_type, band_count, bbox, crs, etc.)"
    )

    # ========================================================================
    # TIMESTAMPS
    # ========================================================================
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when artifact was created"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp of last update"
    )
    deleted_at: Optional[datetime] = Field(
        None,
        description="Soft delete timestamp"
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database storage."""
        return {
            'artifact_id': str(self.artifact_id),
            'content_hash': self.content_hash,
            'storage_account': self.storage_account,
            'container': self.container,
            'blob_path': self.blob_path,
            'size_bytes': self.size_bytes,
            'content_type': self.content_type,
            'blob_version_id': self.blob_version_id,
            'stac_collection_id': self.stac_collection_id,
            'stac_item_id': self.stac_item_id,
            'client_type': self.client_type,
            'client_refs': self.client_refs,
            'source_job_id': self.source_job_id,
            'source_task_id': self.source_task_id,
            'supersedes': str(self.supersedes) if self.supersedes else None,
            'superseded_by': str(self.superseded_by) if self.superseded_by else None,
            'revision': self.revision,
            'status': self.status.value if isinstance(self.status, ArtifactStatus) else self.status,
            'metadata': self.metadata,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'deleted_at': self.deleted_at.isoformat() if self.deleted_at else None,
        }


# ============================================================================
# SCHEMA METADATA - Used by PydanticToSQL generator
# ============================================================================

ARTIFACT_TABLE_NAMES = {
    'Artifact': 'artifacts'
}

ARTIFACT_PRIMARY_KEYS = {
    'Artifact': ['artifact_id']
}

ARTIFACT_INDEXES = {
    'Artifact': [
        ('client_type',),
        ('source_job_id',),
        ('status',),
        ('stac_collection_id', 'stac_item_id'),
        ('created_at',),
    ]
}


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'ArtifactStatus',
    'Artifact',
    'ARTIFACT_TABLE_NAMES',
    'ARTIFACT_PRIMARY_KEYS',
    'ARTIFACT_INDEXES',
]
