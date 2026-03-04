# core/models/release_audit.py
# ============================================================================
# CLAUDE CONTEXT - RELEASE AUDIT LOG MODELS
# ============================================================================
# STATUS: Core - Append-only release lifecycle event tracking
# PURPOSE: Preserve release state transitions before destructive mutations
# CREATED: 03 MAR 2026
# LAST_REVIEWED: 03 MAR 2026
# ============================================================================
"""
Release Audit Log Models.

Append-only event journal that captures release state at each lifecycle
transition. Exists to preserve audit trail when update_overwrite() resets
the release row for resubmission.

This is NOT a restore mechanism. It records what happened.
It does NOT store blob data or enable rollback.

Exports:
    ReleaseAuditEventType: Event type enum
    ReleaseAuditEvent: Database model for audit records

Dependencies:
    pydantic: Data validation
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, ClassVar
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict, field_serializer


# ============================================================================
# ENUMS
# ============================================================================

class ReleaseAuditEventType(str, Enum):
    """
    Release lifecycle events that produce audit records.

    Every state-changing operation on a release row emits one of these.
    OVERWRITTEN is the critical event — it fires before update_overwrite()
    destroys approval/revocation fields.
    """
    CREATED = "created"
    PROCESSING_STARTED = "processing_started"
    PROCESSING_COMPLETED = "processing_completed"
    PROCESSING_FAILED = "processing_failed"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"
    OVERWRITTEN = "overwritten"


# ============================================================================
# DATABASE MODEL
# ============================================================================

class ReleaseAuditEvent(BaseModel):
    """
    Release audit event — append-only lifecycle record.

    Auto-generates:
        CREATE TABLE app.release_audit (
            audit_id BIGSERIAL PRIMARY KEY,
            release_id VARCHAR(64) NOT NULL,
            asset_id VARCHAR(64) NOT NULL,
            version_ordinal INTEGER NOT NULL,
            revision INTEGER NOT NULL,
            event_type app.release_audit_event_type NOT NULL,
            actor VARCHAR(200),
            reason TEXT,
            snapshot JSONB NOT NULL DEFAULT '{}',
            metadata JSONB DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """

    model_config = ConfigDict()

    @field_serializer('created_at')
    @classmethod
    def serialize_datetime(cls, v: datetime) -> Optional[str]:
        return v.isoformat() if v else None

    # ========================================================================
    # SQL DDL METADATA
    # ========================================================================
    __sql_table_name: ClassVar[str] = "release_audit"
    __sql_schema: ClassVar[str] = "app"
    __sql_primary_key: ClassVar[List[str]] = ["audit_id"]
    __sql_serial_columns: ClassVar[List[str]] = ["audit_id"]
    __sql_indexes: ClassVar[List[Dict[str, Any]]] = [
        {"name": "idx_release_audit_release_id", "columns": ["release_id"]},
        {"name": "idx_release_audit_asset_ord", "columns": ["asset_id", "version_ordinal"]},
        {"name": "idx_release_audit_event_type", "columns": ["event_type"]},
        {"name": "idx_release_audit_created_at", "columns": ["created_at"], "descending": True},
    ]

    # ========================================================================
    # PRIMARY KEY (Auto-increment)
    # ========================================================================
    audit_id: Optional[int] = Field(
        None,
        description="Auto-increment audit ID (BIGSERIAL)"
    )

    # ========================================================================
    # RELEASE IDENTITY (denormalized for query efficiency)
    # ========================================================================
    release_id: str = Field(
        ...,
        max_length=64,
        description="Release this event belongs to"
    )
    asset_id: str = Field(
        ...,
        max_length=64,
        description="Asset ID (denormalized — avoids join for ordinal queries)"
    )
    version_ordinal: int = Field(
        ...,
        ge=0,
        description="Ordinal at event time"
    )
    revision: int = Field(
        ...,
        ge=1,
        description="Revision cycle this event belongs to"
    )

    # ========================================================================
    # EVENT DATA
    # ========================================================================
    event_type: ReleaseAuditEventType = Field(
        ...,
        description="Lifecycle event type"
    )
    actor: Optional[str] = Field(
        None,
        max_length=200,
        description="Who triggered the event (user email or 'system')"
    )
    reason: Optional[str] = Field(
        None,
        description="Human-readable reason (revocation reason, rejection reason, etc.)"
    )

    # ========================================================================
    # STATE SNAPSHOT
    # ========================================================================
    snapshot: Dict[str, Any] = Field(
        default_factory=dict,
        description="Frozen release.to_dict() at event time — the 'before' state"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Extensible event-specific data"
    )

    # ========================================================================
    # TIMESTAMP
    # ========================================================================
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this event was recorded"
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database storage."""
        return {
            'audit_id': self.audit_id,
            'release_id': self.release_id,
            'asset_id': self.asset_id,
            'version_ordinal': self.version_ordinal,
            'revision': self.revision,
            'event_type': self.event_type.value if isinstance(self.event_type, ReleaseAuditEventType) else self.event_type,
            'actor': self.actor,
            'reason': self.reason,
            'snapshot': self.snapshot,
            'metadata': self.metadata,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'ReleaseAuditEventType',
    'ReleaseAuditEvent',
]
