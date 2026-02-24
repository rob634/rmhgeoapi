# ============================================================================
# SYSTEM SNAPSHOT DATABASE MODELS
# ============================================================================
# STATUS: Core - SystemSnapshotRecord for configuration drift detection
# PURPOSE: Database representation of system configuration snapshots
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: New file - part of system diagnostics enhancement
# ============================================================================
"""
System Snapshot Database Models.

Defines SystemSnapshotRecord for storing periodic snapshots of Azure platform
configuration. Used for detecting configuration drift in corporate environments
where settings may change without warning.

Captured data includes:
    - Network environment (VNet, ASE, DNS settings)
    - Platform configuration (SKU, region, compute mode)
    - Config sources (which settings come from env vars vs defaults)
    - Instance information (worker count, process details)

Exports:
    SnapshotTriggerType: Enum for what triggered the snapshot
    SystemSnapshotRecord: Pydantic model for snapshot database records

Dependencies:
    pydantic: Data validation
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict, field_serializer


class SnapshotTriggerType(str, Enum):
    """
    What triggered the system snapshot.

    Values:
        STARTUP: Captured during application startup
        SCHEDULED: Captured by scheduled health check
        MANUAL: Captured via admin endpoint
        DRIFT_DETECTED: Captured when config hash changed
    """
    STARTUP = "startup"
    SCHEDULED = "scheduled"
    MANUAL = "manual"
    DRIFT_DETECTED = "drift_detected"


class SystemSnapshotRecord(BaseModel):
    """
    Database representation of a system configuration snapshot.

    Stores a point-in-time snapshot of Azure platform configuration
    for drift detection and audit purposes.

    Key queryable fields are extracted from the full snapshot for
    efficient SQL queries. The full_snapshot JSONB contains the
    complete data for detailed inspection.

    Drift detection:
        - config_hash: SHA256 of key configuration values
        - Compare current hash to previous snapshot
        - If different, has_drift=True and drift_details shows what changed
    """

    model_config = ConfigDict()

    @field_serializer('captured_at')
    @classmethod
    def serialize_datetime(cls, v: datetime) -> Optional[str]:
        return v.isoformat() if v else None

    # Primary key - auto-generated serial
    snapshot_id: Optional[int] = Field(default=None, description="Auto-generated snapshot ID")

    # When and why
    captured_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this snapshot was captured"
    )
    trigger_type: SnapshotTriggerType = Field(
        default=SnapshotTriggerType.MANUAL,
        description="What triggered this snapshot"
    )

    # Instance identification (for multi-instance correlation)
    instance_id: Optional[str] = Field(
        default=None,
        max_length=64,
        description="WEBSITE_INSTANCE_ID of capturing instance"
    )
    role_instance_id: Optional[str] = Field(
        default=None,
        max_length=20,
        description="WEBSITE_ROLE_INSTANCE_ID (short form)"
    )

    # Hash for quick drift detection
    config_hash: str = Field(
        max_length=64,
        description="SHA256 hash of key config values for drift detection"
    )

    # Key queryable fields (extracted from full_snapshot for SQL queries)
    environment_type: Optional[str] = Field(
        default=None,
        max_length=30,
        description="standard, vnet_integrated, or ase"
    )
    sku: Optional[str] = Field(
        default=None,
        max_length=30,
        description="App Service SKU (e.g., PremiumV3)"
    )
    region: Optional[str] = Field(
        default=None,
        max_length=30,
        description="Azure region"
    )

    # VNet/Network settings (critical for connectivity)
    vnet_private_ip: Optional[str] = Field(
        default=None,
        max_length=45,
        description="Private IP if VNet integrated"
    )
    dns_server: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Custom DNS server if configured"
    )
    vnet_route_all: Optional[bool] = Field(
        default=None,
        description="Whether all traffic routes through VNet"
    )

    # Worker/scaling configuration
    worker_process_count: Optional[int] = Field(
        default=None,
        description="FUNCTIONS_WORKER_PROCESS_COUNT"
    )

    # Config quality metrics
    config_from_env_count: int = Field(
        default=0,
        description="Number of configs from environment variables"
    )
    config_defaults_count: int = Field(
        default=0,
        description="Number of configs using defaults (alert if increases!)"
    )
    discovered_var_count: int = Field(
        default=0,
        description="Number of WEBSITE_*/AZURE_* vars discovered"
    )

    # Full snapshot data
    full_snapshot: Dict[str, Any] = Field(
        default_factory=dict,
        description="Complete snapshot from health endpoint components"
    )

    # Drift detection
    has_drift: bool = Field(
        default=False,
        description="True if config_hash differs from previous snapshot"
    )
    drift_details: Optional[Dict[str, Any]] = Field(
        default=None,
        description="What changed from previous snapshot (if has_drift=True)"
    )
    previous_snapshot_id: Optional[int] = Field(
        default=None,
        description="ID of the snapshot this was compared against"
    )

    # Metadata
    app_version: Optional[str] = Field(
        default=None,
        max_length=20,
        description="Application version at capture time"
    )
    notes: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional notes (e.g., reason for manual snapshot)"
    )
