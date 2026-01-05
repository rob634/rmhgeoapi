# ============================================================================
# CLAUDE CONTEXT - OGC STYLES PYDANTIC MODELS
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Data models - CartoSym-JSON and API response schemas
# PURPOSE: Define type-safe models for OGC API Styles
# LAST_REVIEWED: 05 JAN 2026
# EXPORTS: CartoSym* models, OGCStyle* models, Leaflet/Mapbox response models
# DEPENDENCIES: pydantic
# ============================================================================
"""
OGC API Styles Pydantic Models.

Defines schemas for:
- CartoSym-JSON (OGC canonical style format)
- OGC API Styles responses (list, individual style)
- Output format responses (Leaflet, Mapbox GL)

Created: 18 DEC 2025
"""

from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional


# ============================================================================
# OGC LINK MODEL (for API responses)
# ============================================================================

class OGCLink(BaseModel):
    """OGC API link object."""
    rel: str
    href: str
    type: Optional[str] = None
    title: Optional[str] = None
    hreflang: Optional[str] = None


# ============================================================================
# CARTOSYM-JSON MODELS (Canonical Storage Format)
# ============================================================================

class CartoSymFill(BaseModel):
    """CartoSym-JSON fill specification."""
    color: str
    opacity: float = 1.0


class CartoSymStroke(BaseModel):
    """CartoSym-JSON stroke specification."""
    color: str
    width: float = 1.0
    opacity: float = 1.0
    cap: str = "round"
    join: str = "round"


class CartoSymMarker(BaseModel):
    """CartoSym-JSON marker specification for point geometries."""
    size: float = 6
    fill: Optional[CartoSymFill] = None
    stroke: Optional[CartoSymStroke] = None


class CartoSymSymbolizer(BaseModel):
    """CartoSym-JSON symbolizer specification."""
    type: str  # "Polygon", "Line", "Point"
    fill: Optional[CartoSymFill] = None
    stroke: Optional[CartoSymStroke] = None
    marker: Optional[CartoSymMarker] = None


class CartoSymSelector(BaseModel):
    """
    CQL2-JSON selector for data-driven styling.

    Example:
        {"op": "=", "args": [{"property": "iucn_cat"}, "Ia"]}
    """
    op: str  # "=", "<>", ">", "<", ">=", "<="
    args: List[Any]  # [{"property": "field"}, "value"]


class CartoSymRule(BaseModel):
    """CartoSym-JSON styling rule."""
    name: str
    selector: Optional[CartoSymSelector] = None
    symbolizer: CartoSymSymbolizer


class CartoSymStyle(BaseModel):
    """
    CartoSym-JSON style document (canonical format).

    This is the format stored in the database.
    """
    name: str
    title: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    stylingRules: List[CartoSymRule]


# ============================================================================
# OGC API STYLES RESPONSE MODELS
# ============================================================================

class OGCStyleSummary(BaseModel):
    """Style summary for list endpoint."""
    id: str
    title: Optional[str] = None
    description: Optional[str] = None
    default: bool = False
    links: List[OGCLink] = Field(default_factory=list)


class OGCStyleList(BaseModel):
    """
    Response for GET /collections/{id}/styles.

    OGC API - Styles conformance class.
    """
    styles: List[OGCStyleSummary] = Field(default_factory=list)
    links: List[OGCLink] = Field(default_factory=list)


# ============================================================================
# OUTPUT FORMAT RESPONSE MODELS
# ============================================================================

class LeafletStyleRule(BaseModel):
    """A single rule in a data-driven Leaflet style."""
    value: Any
    style: Dict[str, Any]


class LeafletDataDrivenStyle(BaseModel):
    """
    Leaflet data-driven style response.

    Used when CartoSym-JSON contains selectors (data-driven styling).
    """
    type: str = "data-driven"
    property: Optional[str] = None
    rules: List[LeafletStyleRule] = Field(default_factory=list)
    default: Dict[str, Any] = Field(default_factory=dict)
    styleFunction: str = ""


class MapboxStyleResponse(BaseModel):
    """
    Mapbox GL style response.

    Returns a partial Mapbox GL style with layers array.
    Source must be added client-side.
    """
    version: int = 8
    name: str
    layers: List[Dict[str, Any]] = Field(default_factory=list)


# ============================================================================
# DATABASE RECORD MODELS
# ============================================================================

class StyleRecord(BaseModel):
    """
    Style record from database.

    Maps to geo.feature_collection_styles table.
    """
    id: Optional[int] = None
    collection_id: str
    style_id: str
    title: Optional[str] = None
    description: Optional[str] = None
    style_spec: Dict[str, Any]  # CartoSym-JSON document
    is_default: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        """Pydantic config."""
        from_attributes = True
