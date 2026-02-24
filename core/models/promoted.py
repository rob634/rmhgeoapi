# ============================================================================
# PROMOTED DATASET MODELS
# ============================================================================
# STATUS: Core - Dataset promotion and gallery system
# PURPOSE: Metadata layer on top of STAC for featured/gallery display
# LAST_REVIEWED: 03 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
Promoted Dataset Models.

Pydantic models for the dataset promotion system. Promoted datasets are
a metadata layer on top of STAC collections/items that enables:
- Custom titles/descriptions (override STAC metadata)
- Auto-generated thumbnails
- Gallery featuring with ordering
- OGC Styles integration (Phase 2)

Tables:
    app.promoted_datasets - Registry of promoted datasets

Design Principle:
    ALL data is in STAC. This is just a "favorites/featured" layer on top.
    Promoted items reference STAC IDs, never raw storage paths.

Exports:
    PromotedDataset: Registry record for a promoted dataset
    PromotedDatasetType: Type of STAC reference (collection vs item)

Created: 22 DEC 2025
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict, model_validator, field_serializer

from .stac import AccessLevel


class PromotedDatasetType(str, Enum):
    """Type of STAC reference for promoted dataset."""
    COLLECTION = "collection"  # STAC Collection (e.g., fathom-pluvial-undefended)
    ITEM = "item"              # Individual STAC Item


class SystemRole(str, Enum):
    """
    System roles for reserved datasets.

    System-reserved datasets are critical for platform operations.
    They require confirmation to demote and can be discovered by role.
    """
    ADMIN0_BOUNDARIES = "admin0_boundaries"  # Country boundaries for spatial attribution
    H3_LAND_GRID = "h3_land_grid"            # H3 land-only grid cells
    # Future roles:
    # ADMIN1_BOUNDARIES = "admin1_boundaries"  # State/province boundaries
    # COASTLINES = "coastlines"                # Coastline reference data


class PromotedDataset(BaseModel):
    """
    Registry record for a promoted dataset.

    A promoted dataset is a metadata layer on top of STAC that enables:
    - Featured display with custom title/description overrides
    - Auto-generated thumbnails
    - Gallery featuring with ordering
    - OGC Styles integration (Phase 2)

    Design Principle:
        ALL pipeline outputs go to STAC. Promoted datasets just reference
        STAC collection_id or item_id - never raw storage paths.

    Table: app.promoted_datasets
    Primary Key: promoted_id

    Examples:
        # Promote a STAC collection
        PromotedDataset(
            promoted_id="fathom-flood-100yr",
            stac_collection_id="fathom-pluvial-undefended",
            title="FATHOM 100-Year Flood Depth",
            tags=["flood", "hazard", "fathom"]
        )

        # Promote an individual STAC item
        PromotedDataset(
            promoted_id="chile-admin-boundaries",
            stac_item_id="admin-boundaries-chile-v1",
            title="Chile Administrative Boundaries"
        )
    """

    model_config = ConfigDict()

    @field_serializer('thumbnail_generated_at', 'promoted_at', 'updated_at')
    @classmethod
    def serialize_datetime(cls, v: datetime) -> Optional[str]:
        return v.isoformat() if v else None

    # Identity
    promoted_id: str = Field(
        ...,
        max_length=64,
        description="Unique identifier (slug format, e.g., 'fathom-flood-100yr')"
    )

    # STAC Reference (exactly one required)
    stac_collection_id: Optional[str] = Field(
        default=None,
        max_length=100,
        description="STAC collection ID (mutually exclusive with stac_item_id)"
    )
    stac_item_id: Optional[str] = Field(
        default=None,
        max_length=100,
        description="STAC item ID (mutually exclusive with stac_collection_id)"
    )

    # Display Overrides (optional - falls back to STAC metadata if NULL)
    title: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Override STAC title for display"
    )
    description: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Override STAC description for display"
    )

    # Thumbnail
    thumbnail_url: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Auto-generated or custom thumbnail URL"
    )
    thumbnail_generated_at: Optional[datetime] = Field(
        default=None,
        description="When thumbnail was last generated"
    )

    # Categorization
    tags: List[str] = Field(
        default_factory=list,
        description="Tags for categorization (e.g., ['flood', 'hazard', 'fathom'])"
    )

    # Viewer Configuration
    viewer_config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Custom viewer settings (center, zoom, etc.)"
    )
    style_id: Optional[str] = Field(
        default=None,
        max_length=64,
        description="OGC Style ID for rendering (Phase 2)"
    )

    # Gallery
    in_gallery: bool = Field(
        default=False,
        description="Whether this item appears in the gallery"
    )
    gallery_order: Optional[int] = Field(
        default=None,
        ge=1,
        description="Display order in gallery (1 = first). NULL if not in gallery."
    )

    # System Reserved (23 DEC 2025)
    is_system_reserved: bool = Field(
        default=False,
        description="If True, dataset is critical for system operations and protected from accidental demotion"
    )
    system_role: Optional[str] = Field(
        default=None,
        max_length=50,
        description="System role identifier (e.g., 'admin0_boundaries'). Enables lookup by role."
    )

    # Classification (23 DEC 2025, unified 25 JAN 2026 - S4.DM.1)
    # NOTE: RESTRICTED is defined in AccessLevel but NOT YET SUPPORTED
    classification: AccessLevel = Field(
        default=AccessLevel.PUBLIC,
        description="Data access classification (public, ouo). RESTRICTED not yet supported."
    )

    # Audit
    promoted_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this item was promoted"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this record was last modified"
    )

    @model_validator(mode='after')
    def validate_stac_reference(self):
        """Ensure exactly one STAC reference is provided."""
        has_collection = self.stac_collection_id is not None
        has_item = self.stac_item_id is not None

        if has_collection and has_item:
            raise ValueError(
                "Cannot specify both stac_collection_id and stac_item_id. "
                "Choose one STAC reference type."
            )
        if not has_collection and not has_item:
            raise ValueError(
                "Must specify either stac_collection_id or stac_item_id. "
                "Promoted datasets reference STAC, not raw storage."
            )
        return self

    @property
    def stac_type(self) -> PromotedDatasetType:
        """Return the type of STAC reference."""
        if self.stac_collection_id:
            return PromotedDatasetType.COLLECTION
        return PromotedDatasetType.ITEM

    @property
    def stac_id(self) -> str:
        """Return the STAC ID (either collection or item)."""
        return self.stac_collection_id or self.stac_item_id


# Module exports
# NOTE: Classification enum REMOVED (25 JAN 2026) - use AccessLevel from stac.py instead
__all__ = [
    'PromotedDataset',
    'PromotedDatasetType',
    'SystemRole',
]
