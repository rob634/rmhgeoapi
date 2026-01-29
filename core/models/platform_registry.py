# ============================================================================
# PLATFORM REGISTRY MODEL
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Core - B2B platform registry for flexible asset identification
# PURPOSE: Define Platform model for multi-platform support in V0.8
# CREATED: 29 JAN 2026
# EXPORTS: Platform
# DEPENDENCIES: pydantic, datetime
# ============================================================================
"""
Platform Registry Model.

Defines valid B2B platforms and their identifier requirements.
Enables flexible asset lookups by arbitrary platform-specific identifiers.

Architecture:
    - Platform: Registry entry defining a B2B integration
    - required_refs: Keys that MUST be present in platform_refs
    - optional_refs: Keys that MAY be present in platform_refs

Design Decisions (documented in V0.8_ENTITIES.md Section 14):
    - Platform defines schema, not data
    - GeospatialAsset stores platform_id + platform_refs (JSONB)
    - GIN index enables efficient containment queries
    - DDH is seeded as default platform

Table Auto-Generated (stored in app schema):
    - app.platforms

Created: 29 JAN 2026 as part of V0.8 Entity Architecture
"""

from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, ClassVar
from pydantic import BaseModel, Field, ConfigDict


class Platform(BaseModel):
    """
    Registry entry for a B2B platform integration.

    Defines what identifiers a platform requires/supports for asset lookup.

    Table: app.platforms
    Primary Key: platform_id

    Example:
        Platform(
            platform_id="ddh",
            display_name="Data Distribution Hub",
            required_refs=["dataset_id", "resource_id", "version_id"],
            optional_refs=["title", "description"]
        )
    """
    model_config = ConfigDict(
        use_enum_values=True,
        extra='ignore',
        str_strip_whitespace=True,
        json_encoders={datetime: lambda v: v.isoformat() if v else None}
    )

    # =========================================================================
    # DDL GENERATION HINTS (ClassVar = not a model field)
    # =========================================================================
    __sql_table_name: ClassVar[str] = "platforms"
    __sql_schema: ClassVar[str] = "app"
    __sql_primary_key: ClassVar[List[str]] = ["platform_id"]
    __sql_indexes: ClassVar[List[Dict[str, Any]]] = [
        {
            "columns": ["is_active"],
            "name": "idx_platforms_active",
            "partial_where": "is_active = true"
        },
    ]

    # =========================================================================
    # IDENTITY
    # =========================================================================
    platform_id: str = Field(
        ...,
        max_length=50,
        pattern=r'^[a-z][a-z0-9_]*$',
        description="Unique platform identifier (lowercase, underscores allowed)"
    )

    # =========================================================================
    # METADATA
    # =========================================================================
    display_name: str = Field(
        ...,
        max_length=100,
        description="Human-readable platform name"
    )
    description: Optional[str] = Field(
        default=None,
        description="Platform description"
    )

    # =========================================================================
    # IDENTIFIER SCHEMA
    # =========================================================================
    required_refs: List[str] = Field(
        default_factory=list,
        description="Required keys in platform_refs (e.g., ['dataset_id', 'resource_id', 'version_id'])"
    )
    optional_refs: List[str] = Field(
        default_factory=list,
        description="Optional keys in platform_refs"
    )

    # =========================================================================
    # STATUS
    # =========================================================================
    is_active: bool = Field(
        default=True,
        description="Whether platform accepts new submissions"
    )

    # =========================================================================
    # TIMESTAMPS
    # =========================================================================
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When platform was registered"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When platform was last modified"
    )

    # =========================================================================
    # HELPER METHODS
    # =========================================================================
    def validate_refs(self, refs: Dict[str, Any]) -> List[str]:
        """
        Validate that refs contains all required keys.

        Args:
            refs: Dictionary of platform-specific identifiers

        Returns:
            List of missing required keys (empty if valid)
        """
        missing = []
        for key in self.required_refs:
            if key not in refs or refs[key] is None:
                missing.append(key)
        return missing

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database storage."""
        return {
            'platform_id': self.platform_id,
            'display_name': self.display_name,
            'description': self.description,
            'required_refs': self.required_refs,
            'optional_refs': self.optional_refs,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


# ============================================================================
# DEFAULT PLATFORMS
# ============================================================================

# DDH (Data Distribution Hub) - Primary B2B platform
DDH_PLATFORM = Platform(
    platform_id="ddh",
    display_name="Data Distribution Hub",
    description="Primary B2B integration platform with dataset/resource/version hierarchy",
    required_refs=["dataset_id", "resource_id", "version_id"],
    optional_refs=["title", "description", "access_level"],
    is_active=True
)


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'Platform',
    'DDH_PLATFORM',
]
