# OGC API Styles Implementation Plan

**Status**: 📋 PLANNING COMPLETE - Ready for Implementation
**Created**: 17 DEC 2025
**Referenced By**: `docs_claude/TODO.md` (HIGH PRIORITY #2)

---

## Overview

Implement OGC API - Styles endpoints for the existing OGC Features API. Store styles in CartoSym-JSON format and serve multiple output encodings (Leaflet, Mapbox GL) on demand.

**Key Insight**: The existing `ogc_features/` module provides a clean foundation. This implementation follows the same patterns (triggers, service, repository) with minimal additions.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  PostgreSQL                                                     │
│  ┌──────────────────────┐    ┌───────────────────────────────┐  │
│  │ geo.* tables         │    │ geo.feature_collection_styles │  │
│  │ (PostGIS geometry)   │    │ (CartoSym-JSON source)        │  │
│  └──────────────────────┘    └───────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                │                          │
                ▼                          ▼
┌─────────────────────────────────────────────────────────────────┐
│  Azure Function App (OGC API)                                   │
│                                                                 │
│  GET /features/collections/{id}/items     → GeoJSON features    │
│  GET /features/collections/{id}/styles    → list styles         │
│  GET /features/collections/{id}/styles/{sid} → style document   │
│       ?f=cartosym  → CartoSym-JSON (canonical)                  │
│       ?f=leaflet   → Leaflet style object/function              │
│       ?f=mapbox    → Mapbox GL style layers                     │
└─────────────────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────────┐
│  Client Applications                                            │
│  - Leaflet web maps (static + data-driven styles)               │
│  - MapLibre GL / Mapbox GL                                      │
│  - OpenLayers (future)                                          │
└─────────────────────────────────────────────────────────────────┘
```

---

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `ogc_features/style_translator.py` | **CREATE** | CartoSym → Leaflet/Mapbox conversion |
| `ogc_features/triggers.py` | **MODIFY** | Add 2 new trigger classes |
| `ogc_features/repository.py` | **MODIFY** | Add style query methods |
| `ogc_features/service.py` | **MODIFY** | Add style orchestration |
| `ogc_features/models.py` | **MODIFY** | Add Pydantic models for styles |
| `core/schema/sql_generator.py` | **MODIFY** | Add `geo.feature_collection_styles` table |
| `function_app.py` | **MODIFY** | Register new style triggers |

---

## Database Schema

Add to `core/schema/sql_generator.py` for `geo` schema:

```sql
-- OGC API Styles: CartoSym-JSON storage
-- Added: 17 DEC 2025
CREATE TABLE IF NOT EXISTS geo.feature_collection_styles (
    id SERIAL PRIMARY KEY,
    collection_id TEXT NOT NULL,           -- matches OGC Features collection (table name)
    style_id TEXT NOT NULL,                -- url-safe identifier (e.g., "default", "by-category")
    title TEXT,                            -- human-readable title
    description TEXT,                      -- style description
    style_spec JSONB NOT NULL,             -- CartoSym-JSON document
    is_default BOOLEAN DEFAULT false,      -- default style for collection
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(collection_id, style_id)
);

-- Index for fast lookups by collection
CREATE INDEX IF NOT EXISTS idx_styles_collection
ON geo.feature_collection_styles(collection_id);

-- Ensure only one default per collection (partial unique index)
CREATE UNIQUE INDEX IF NOT EXISTS idx_styles_default
ON geo.feature_collection_styles(collection_id)
WHERE is_default = true;

COMMENT ON TABLE geo.feature_collection_styles IS
'OGC API Styles: CartoSym-JSON storage with multi-format output (Leaflet, Mapbox GL)';
```

---

## Implementation Code

### 1. Pydantic Models (`ogc_features/models.py`)

Add these models to the existing `models.py`:

```python
# ============================================================================
# OGC API STYLES MODELS (17 DEC 2025)
# ============================================================================

class OGCStyleSummary(BaseModel):
    """Style summary for list endpoint."""
    id: str
    title: Optional[str] = None
    description: Optional[str] = None
    default: bool = False
    links: List[OGCLink] = []


class OGCStyleList(BaseModel):
    """Response for GET /collections/{id}/styles."""
    styles: List[OGCStyleSummary] = []
    links: List[OGCLink] = []


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
    """CartoSym-JSON marker specification."""
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
    """CQL2-JSON selector for data-driven styling."""
    op: str  # "=", "<>", ">", "<", ">=", "<="
    args: List[Any]  # [{"property": "field"}, "value"]


class CartoSymRule(BaseModel):
    """CartoSym-JSON styling rule."""
    name: str
    selector: Optional[CartoSymSelector] = None
    symbolizer: CartoSymSymbolizer


class CartoSymStyle(BaseModel):
    """CartoSym-JSON style document (canonical format)."""
    name: str
    title: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    stylingRules: List[CartoSymRule]


class LeafletDataDrivenStyle(BaseModel):
    """Leaflet data-driven style response."""
    type: str = "data-driven"
    property: Optional[str] = None
    rules: List[Dict[str, Any]] = []
    default: Dict[str, Any] = {}
    styleFunction: str = ""


class MapboxStyleResponse(BaseModel):
    """Mapbox GL style response."""
    version: int = 8
    name: str
    layers: List[Dict[str, Any]] = []
```

---

### 2. Style Translator (`ogc_features/style_translator.py`)

```python
"""
OGC API Styles translator service.

Translates CartoSym-JSON to various output formats (Leaflet, Mapbox GL).

Exports:
    StyleTranslator: Translator for CartoSym-JSON to client formats

Dependencies:
    Standard library only (json, typing)

Created: 17 DEC 2025
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class StyleTranslator:
    """
    Translates CartoSym-JSON to various output formats.

    Supported output formats:
    - Leaflet (static and data-driven)
    - Mapbox GL (layer definitions)

    CartoSym-JSON is the OGC-native canonical format stored in the database.
    """

    def __init__(self, cartosym: Dict[str, Any]):
        """
        Initialize translator with CartoSym-JSON document.

        Args:
            cartosym: CartoSym-JSON style document
        """
        self.cartosym = cartosym
        self.rules = cartosym.get("stylingRules", [])

    # ========================================================================
    # LEAFLET OUTPUT
    # ========================================================================

    def to_leaflet(self) -> Dict[str, Any]:
        """
        Convert CartoSym-JSON to Leaflet-compatible format.

        Returns either:
        - A static style object (if no selectors)
        - A style specification with rules and generated function (if data-driven)
        """
        has_selectors = any(rule.get("selector") for rule in self.rules)

        if has_selectors:
            return self._to_leaflet_data_driven()
        else:
            return self._to_leaflet_static()

    def _to_leaflet_static(self) -> Dict[str, Any]:
        """Convert simple style to static Leaflet style object."""
        polygon_rule = self._find_rule_by_type("Polygon")
        line_rule = self._find_rule_by_type("Line")
        point_rule = self._find_rule_by_type("Point")

        style = {}

        if polygon_rule:
            sym = polygon_rule["symbolizer"]
            style.update({
                "fillColor": sym.get("fill", {}).get("color"),
                "fillOpacity": sym.get("fill", {}).get("opacity", 1),
                "color": sym.get("stroke", {}).get("color"),
                "weight": sym.get("stroke", {}).get("width", 1),
                "opacity": sym.get("stroke", {}).get("opacity", 1),
                "lineCap": sym.get("stroke", {}).get("cap", "round"),
                "lineJoin": sym.get("stroke", {}).get("join", "round")
            })

        if line_rule:
            sym = line_rule["symbolizer"]
            style.update({
                "color": sym.get("stroke", {}).get("color"),
                "weight": sym.get("stroke", {}).get("width", 1),
                "opacity": sym.get("stroke", {}).get("opacity", 1),
                "lineCap": sym.get("stroke", {}).get("cap", "round"),
                "lineJoin": sym.get("stroke", {}).get("join", "round")
            })

        if point_rule:
            sym = point_rule["symbolizer"]
            marker = sym.get("marker", {})
            style.update({
                "radius": marker.get("size", 6),
                "fillColor": marker.get("fill", {}).get("color"),
                "fillOpacity": marker.get("fill", {}).get("opacity", 1),
                "color": marker.get("stroke", {}).get("color"),
                "weight": marker.get("stroke", {}).get("width", 1)
            })

        # Remove None values for cleaner output
        return {k: v for k, v in style.items() if v is not None}

    def _to_leaflet_data_driven(self) -> Dict[str, Any]:
        """
        Convert data-driven style to Leaflet rules format.

        Returns a structure with rules and generated style function:
        {
            "type": "data-driven",
            "property": "iucn_cat",
            "rules": [
                {"value": "Ia", "style": {...}},
                {"value": "Ib", "style": {...}}
            ],
            "default": {...},
            "styleFunction": "function(feature) { ... }"
        }
        """
        rules = []
        default_style = None
        property_name = None

        for rule in self.rules:
            selector = rule.get("selector")
            leaflet_style = self._symbolizer_to_leaflet(rule["symbolizer"])

            if selector:
                # Extract property name and value from CQL2-JSON
                prop, value = self._parse_selector(selector)
                if prop:
                    property_name = prop
                    rules.append({
                        "value": value,
                        "style": leaflet_style
                    })
            else:
                # Rule without selector is the fallback/default
                default_style = leaflet_style

        return {
            "type": "data-driven",
            "property": property_name,
            "rules": rules,
            "default": default_style or {},
            "styleFunction": self._generate_style_function_code(property_name, rules, default_style)
        }

    def _symbolizer_to_leaflet(self, symbolizer: Dict[str, Any]) -> Dict[str, Any]:
        """Convert a single symbolizer to Leaflet style."""
        sym_type = symbolizer.get("type")
        style = {}

        if sym_type == "Polygon":
            fill = symbolizer.get("fill", {})
            stroke = symbolizer.get("stroke", {})
            style = {
                "fillColor": fill.get("color"),
                "fillOpacity": fill.get("opacity", 1),
                "color": stroke.get("color"),
                "weight": stroke.get("width", 1),
                "opacity": stroke.get("opacity", 1),
                "lineCap": stroke.get("cap", "round"),
                "lineJoin": stroke.get("join", "round")
            }
        elif sym_type == "Line":
            stroke = symbolizer.get("stroke", {})
            style = {
                "color": stroke.get("color"),
                "weight": stroke.get("width", 1),
                "opacity": stroke.get("opacity", 1),
                "lineCap": stroke.get("cap", "round"),
                "lineJoin": stroke.get("join", "round")
            }
        elif sym_type == "Point":
            marker = symbolizer.get("marker", {})
            style = {
                "radius": marker.get("size", 6),
                "fillColor": marker.get("fill", {}).get("color"),
                "fillOpacity": marker.get("fill", {}).get("opacity", 1),
                "color": marker.get("stroke", {}).get("color"),
                "weight": marker.get("stroke", {}).get("width", 1)
            }

        return {k: v for k, v in style.items() if v is not None}

    def _parse_selector(self, selector: Dict[str, Any]) -> Tuple[Optional[str], Any]:
        """
        Parse CQL2-JSON selector to extract property name and value.

        Handles simple equality: {"op": "=", "args": [{"property": "x"}, "value"]}
        """
        if selector.get("op") == "=":
            args = selector.get("args", [])
            if len(args) == 2:
                prop_arg = args[0]
                value_arg = args[1]
                if isinstance(prop_arg, dict) and "property" in prop_arg:
                    return prop_arg["property"], value_arg
        return None, None

    def _generate_style_function_code(
        self,
        property_name: Optional[str],
        rules: List[Dict[str, Any]],
        default: Optional[Dict[str, Any]]
    ) -> str:
        """
        Generate JavaScript code for a Leaflet style function.

        This can be eval'd client-side or used as reference.
        """
        if not property_name or not rules:
            return f"function(feature) {{ return {json.dumps(default or {})}; }}"

        conditions = []
        for rule in rules:
            value = rule["value"]
            style_json = json.dumps(rule["style"])
            if isinstance(value, str):
                conditions.append(f'  if (props.{property_name} === "{value}") return {style_json};')
            else:
                conditions.append(f'  if (props.{property_name} === {value}) return {style_json};')

        default_json = json.dumps(default or {})

        return f"""function(feature) {{
  const props = feature.properties || {{}};
{chr(10).join(conditions)}
  return {default_json};
}}"""

    def _find_rule_by_type(self, sym_type: str) -> Optional[Dict[str, Any]]:
        """Find first rule matching symbolizer type."""
        for rule in self.rules:
            if rule.get("symbolizer", {}).get("type") == sym_type:
                return rule
        return None

    # ========================================================================
    # MAPBOX GL OUTPUT
    # ========================================================================

    def to_mapbox(self) -> Dict[str, Any]:
        """
        Convert CartoSym-JSON to Mapbox GL style layers.

        Returns a partial Mapbox GL style with layers array.
        """
        layers = []

        for rule in self.rules:
            symbolizer = rule["symbolizer"]
            sym_type = symbolizer.get("type")
            layer_id = rule.get("name", "layer")

            if sym_type == "Polygon":
                # Fill layer
                fill_layer = {
                    "id": f"{layer_id}-fill",
                    "type": "fill",
                    "paint": {
                        "fill-color": symbolizer.get("fill", {}).get("color", "#000000"),
                        "fill-opacity": symbolizer.get("fill", {}).get("opacity", 1)
                    }
                }

                # Add filter if selector present
                selector = rule.get("selector")
                if selector:
                    fill_layer["filter"] = self._selector_to_mapbox_filter(selector)

                layers.append(fill_layer)

                # Stroke layer
                stroke = symbolizer.get("stroke", {})
                if stroke:
                    stroke_layer = {
                        "id": f"{layer_id}-stroke",
                        "type": "line",
                        "paint": {
                            "line-color": stroke.get("color", "#000000"),
                            "line-width": stroke.get("width", 1),
                            "line-opacity": stroke.get("opacity", 1)
                        },
                        "layout": {
                            "line-cap": stroke.get("cap", "round"),
                            "line-join": stroke.get("join", "round")
                        }
                    }
                    if selector:
                        stroke_layer["filter"] = self._selector_to_mapbox_filter(selector)
                    layers.append(stroke_layer)

            elif sym_type == "Line":
                stroke = symbolizer.get("stroke", {})
                line_layer = {
                    "id": layer_id,
                    "type": "line",
                    "paint": {
                        "line-color": stroke.get("color", "#000000"),
                        "line-width": stroke.get("width", 1),
                        "line-opacity": stroke.get("opacity", 1)
                    },
                    "layout": {
                        "line-cap": stroke.get("cap", "round"),
                        "line-join": stroke.get("join", "round")
                    }
                }
                selector = rule.get("selector")
                if selector:
                    line_layer["filter"] = self._selector_to_mapbox_filter(selector)
                layers.append(line_layer)

            elif sym_type == "Point":
                marker = symbolizer.get("marker", {})
                circle_layer = {
                    "id": layer_id,
                    "type": "circle",
                    "paint": {
                        "circle-radius": marker.get("size", 6),
                        "circle-color": marker.get("fill", {}).get("color", "#000000"),
                        "circle-opacity": marker.get("fill", {}).get("opacity", 1),
                        "circle-stroke-color": marker.get("stroke", {}).get("color", "#000000"),
                        "circle-stroke-width": marker.get("stroke", {}).get("width", 1)
                    }
                }
                selector = rule.get("selector")
                if selector:
                    circle_layer["filter"] = self._selector_to_mapbox_filter(selector)
                layers.append(circle_layer)

        return {
            "version": 8,
            "name": self.cartosym.get("name", "style"),
            "layers": layers
        }

    def _selector_to_mapbox_filter(self, selector: Dict[str, Any]) -> List[Any]:
        """
        Convert CQL2-JSON selector to Mapbox GL filter expression.

        CQL2: {"op": "=", "args": [{"property": "x"}, "value"]}
        Mapbox: ["==", ["get", "x"], "value"]
        """
        op = selector.get("op")
        args = selector.get("args", [])

        op_map = {
            "=": "==",
            "<>": "!=",
            ">": ">",
            "<": "<",
            ">=": ">=",
            "<=": "<="
        }

        if op in op_map and len(args) == 2:
            prop_arg = args[0]
            value_arg = args[1]
            if isinstance(prop_arg, dict) and "property" in prop_arg:
                return [op_map[op], ["get", prop_arg["property"]], value_arg]

        return ["all"]  # fallback: match everything
```

---

### 3. Repository Methods (`ogc_features/repository.py`)

Add these methods to `OGCFeaturesRepository`:

```python
    # ========================================================================
    # STYLE QUERIES (17 DEC 2025)
    # ========================================================================

    def list_styles(self, collection_id: str) -> List[Dict[str, Any]]:
        """
        List all styles for a collection.

        Args:
            collection_id: Collection identifier (table name)

        Returns:
            List of style metadata dicts
        """
        query = sql.SQL("""
            SELECT style_id, title, description, is_default
            FROM geo.feature_collection_styles
            WHERE collection_id = %s
            ORDER BY is_default DESC, title ASC
        """)

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (collection_id,))
                    results = cur.fetchall()
                    logger.info(f"Found {len(results)} styles for collection '{collection_id}'")
                    return results
        except psycopg.Error as e:
            logger.error(f"Error listing styles for '{collection_id}': {e}")
            raise

    def get_style(self, collection_id: str, style_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific style document.

        Args:
            collection_id: Collection identifier
            style_id: Style identifier

        Returns:
            Style dict with style_spec (CartoSym-JSON), or None if not found
        """
        query = sql.SQL("""
            SELECT style_id, title, description, style_spec, is_default
            FROM geo.feature_collection_styles
            WHERE collection_id = %s AND style_id = %s
        """)

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (collection_id, style_id))
                    result = cur.fetchone()
                    if result:
                        logger.info(f"Retrieved style '{style_id}' for collection '{collection_id}'")
                    return result
        except psycopg.Error as e:
            logger.error(f"Error getting style '{style_id}' for '{collection_id}': {e}")
            raise

    def get_default_style(self, collection_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the default style for a collection.

        Args:
            collection_id: Collection identifier

        Returns:
            Default style dict, or None if no default exists
        """
        query = sql.SQL("""
            SELECT style_id, title, description, style_spec, is_default
            FROM geo.feature_collection_styles
            WHERE collection_id = %s AND is_default = true
            LIMIT 1
        """)

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (collection_id,))
                    return cur.fetchone()
        except psycopg.Error as e:
            logger.error(f"Error getting default style for '{collection_id}': {e}")
            raise

    def create_style(
        self,
        collection_id: str,
        style_id: str,
        style_spec: Dict[str, Any],
        title: Optional[str] = None,
        description: Optional[str] = None,
        is_default: bool = False
    ) -> bool:
        """
        Create or update a style for a collection.

        Uses upsert (INSERT ... ON CONFLICT UPDATE) for idempotency.

        Args:
            collection_id: Collection identifier
            style_id: Style identifier (url-safe)
            style_spec: CartoSym-JSON document
            title: Human-readable title
            description: Style description
            is_default: Whether this is the default style

        Returns:
            True if created/updated successfully
        """
        import json

        # If setting as default, first unset any existing default
        if is_default:
            unset_query = sql.SQL("""
                UPDATE geo.feature_collection_styles
                SET is_default = false, updated_at = now()
                WHERE collection_id = %s AND is_default = true
            """)

        upsert_query = sql.SQL("""
            INSERT INTO geo.feature_collection_styles
            (collection_id, style_id, title, description, style_spec, is_default)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (collection_id, style_id) DO UPDATE
            SET title = EXCLUDED.title,
                description = EXCLUDED.description,
                style_spec = EXCLUDED.style_spec,
                is_default = EXCLUDED.is_default,
                updated_at = now()
        """)

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    if is_default:
                        cur.execute(unset_query, (collection_id,))
                    cur.execute(upsert_query, (
                        collection_id,
                        style_id,
                        title,
                        description,
                        json.dumps(style_spec),
                        is_default
                    ))
                    conn.commit()
                    logger.info(f"Created/updated style '{style_id}' for collection '{collection_id}'")
                    return True
        except psycopg.Error as e:
            logger.error(f"Error creating style '{style_id}' for '{collection_id}': {e}")
            raise

    def create_default_style_for_collection(
        self,
        collection_id: str,
        geometry_type: str,
        fill_color: str = "#3388ff",
        stroke_color: str = "#2266cc"
    ) -> bool:
        """
        Create a default style for a collection based on geometry type.

        Called from ETL pipeline after table creation.

        Args:
            collection_id: Collection identifier (table name)
            geometry_type: PostGIS geometry type (Polygon, LineString, Point, etc.)
            fill_color: Fill color (hex)
            stroke_color: Stroke color (hex)

        Returns:
            True if created successfully
        """
        # Normalize geometry type
        geom_type_map = {
            "POLYGON": "Polygon",
            "MULTIPOLYGON": "Polygon",
            "LINESTRING": "Line",
            "MULTILINESTRING": "Line",
            "POINT": "Point",
            "MULTIPOINT": "Point"
        }
        sym_type = geom_type_map.get(geometry_type.upper(), "Polygon")

        # Build CartoSym-JSON based on geometry type
        if sym_type == "Polygon":
            style_spec = {
                "name": f"{collection_id}-default",
                "title": f"Default style for {collection_id}",
                "stylingRules": [{
                    "name": "default",
                    "symbolizer": {
                        "type": "Polygon",
                        "fill": {"color": fill_color, "opacity": 0.6},
                        "stroke": {"color": stroke_color, "width": 1.5}
                    }
                }]
            }
        elif sym_type == "Line":
            style_spec = {
                "name": f"{collection_id}-default",
                "title": f"Default style for {collection_id}",
                "stylingRules": [{
                    "name": "default",
                    "symbolizer": {
                        "type": "Line",
                        "stroke": {"color": stroke_color, "width": 2}
                    }
                }]
            }
        else:  # Point
            style_spec = {
                "name": f"{collection_id}-default",
                "title": f"Default style for {collection_id}",
                "stylingRules": [{
                    "name": "default",
                    "symbolizer": {
                        "type": "Point",
                        "marker": {
                            "size": 8,
                            "fill": {"color": fill_color},
                            "stroke": {"color": stroke_color, "width": 1}
                        }
                    }
                }]
            }

        return self.create_style(
            collection_id=collection_id,
            style_id="default",
            style_spec=style_spec,
            title=style_spec["title"],
            description=f"Auto-generated default style for {collection_id}",
            is_default=True
        )
```

---

### 4. Service Methods (`ogc_features/service.py`)

Add these methods to `OGCFeaturesService`:

```python
    # ========================================================================
    # STYLE OPERATIONS (17 DEC 2025)
    # ========================================================================

    def list_styles(self, collection_id: str, base_url: str) -> Dict[str, Any]:
        """
        List available styles for a collection.

        Args:
            collection_id: Collection identifier
            base_url: Base URL for link generation

        Returns:
            OGC API Styles list response
        """
        # Verify collection exists
        try:
            self.repository.get_collection_metadata(collection_id)
        except ValueError:
            raise ValueError(f"Collection '{collection_id}' not found")

        # Get styles from repository
        styles_data = self.repository.list_styles(collection_id)

        styles_url = f"{base_url}/api/features/collections/{collection_id}/styles"

        styles = []
        for row in styles_data:
            style_entry = {
                "id": row["style_id"],
                "title": row["title"],
                "description": row["description"],
                "default": row["is_default"],
                "links": [
                    {
                        "rel": "describedby",
                        "href": f"{styles_url}/{row['style_id']}",
                        "type": "application/vnd.ogc.cartosym+json",
                        "title": "CartoSym-JSON (canonical)"
                    },
                    {
                        "rel": "describedby",
                        "href": f"{styles_url}/{row['style_id']}?f=leaflet",
                        "type": "application/vnd.leaflet.style+json",
                        "title": "Leaflet style"
                    },
                    {
                        "rel": "describedby",
                        "href": f"{styles_url}/{row['style_id']}?f=mapbox",
                        "type": "application/vnd.mapbox.style+json",
                        "title": "Mapbox GL style"
                    }
                ]
            }
            styles.append(style_entry)

        return {
            "styles": styles,
            "links": [
                {
                    "rel": "self",
                    "href": styles_url,
                    "type": "application/json"
                }
            ]
        }

    def get_style(
        self,
        collection_id: str,
        style_id: str,
        output_format: str = "leaflet"
    ) -> Tuple[Dict[str, Any], str]:
        """
        Get a style document in the requested format.

        Args:
            collection_id: Collection identifier
            style_id: Style identifier
            output_format: Output format (cartosym, leaflet, mapbox)

        Returns:
            Tuple of (style_document, content_type)

        Raises:
            ValueError: If style not found or format unsupported
        """
        from .style_translator import StyleTranslator

        CONTENT_TYPES = {
            "cartosym": "application/vnd.ogc.cartosym+json",
            "leaflet": "application/vnd.leaflet.style+json",
            "mapbox": "application/vnd.mapbox.style+json"
        }

        # Get style from repository
        style_data = self.repository.get_style(collection_id, style_id)

        if not style_data:
            raise ValueError(f"Style '{style_id}' not found for collection '{collection_id}'")

        cartosym = style_data["style_spec"]

        # Return canonical format
        if output_format == "cartosym":
            return cartosym, CONTENT_TYPES["cartosym"]

        # Translate to requested format
        translator = StyleTranslator(cartosym)

        if output_format == "leaflet":
            return translator.to_leaflet(), CONTENT_TYPES["leaflet"]
        elif output_format == "mapbox":
            return translator.to_mapbox(), CONTENT_TYPES["mapbox"]
        else:
            raise ValueError(f"Unsupported output format: {output_format}")
```

---

### 5. Trigger Classes (`ogc_features/triggers.py`)

Add these trigger classes and update `get_ogc_triggers()`:

```python
# ============================================================================
# STYLE TRIGGERS (17 DEC 2025)
# ============================================================================

class OGCStylesListTrigger(BaseOGCTrigger):
    """
    Styles list trigger.

    Endpoint: GET /api/features/collections/{collection_id}/styles
    OGC Conformance: /req/core/styles-list
    """

    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Handle styles list request.

        Args:
            req: Azure Functions HTTP request

        Returns:
            HttpResponse with styles list JSON
        """
        try:
            collection_id = req.route_params.get('collection_id')
            if not collection_id:
                return self._error_response(
                    message="Collection ID is required",
                    status_code=400
                )

            base_url = self._get_base_url(req)
            styles_list = self.service.list_styles(collection_id, base_url)

            logger.info(f"Styles list requested for collection '{collection_id}'")

            return self._json_response(styles_list)

        except ValueError as e:
            logger.warning(f"Collection not found: {e}")
            return self._error_response(
                message=str(e),
                status_code=404,
                error_type="NotFound"
            )
        except Exception as e:
            logger.error(f"Error listing styles: {e}")
            return self._error_response(
                message=f"Internal server error: {str(e)}",
                status_code=500,
                error_type="InternalServerError"
            )


class OGCStyleTrigger(BaseOGCTrigger):
    """
    Single style trigger.

    Endpoint: GET /api/features/collections/{collection_id}/styles/{style_id}
    OGC Conformance: /req/core/style

    Supports content negotiation via:
    - Query parameter: ?f=leaflet, ?f=mapbox, ?f=cartosym
    - Accept header: application/vnd.leaflet.style+json, etc.
    """

    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Handle single style request.

        Args:
            req: Azure Functions HTTP request

        Returns:
            HttpResponse with style document in requested format
        """
        try:
            collection_id = req.route_params.get('collection_id')
            style_id = req.route_params.get('style_id')

            if not collection_id or not style_id:
                return self._error_response(
                    message="Collection ID and Style ID are required",
                    status_code=400
                )

            # Determine output format (query param takes precedence)
            output_format = req.params.get("f", "").lower()
            if not output_format:
                output_format = self._negotiate_format(req.headers.get("Accept", ""))

            # Get style in requested format
            style_doc, content_type = self.service.get_style(
                collection_id=collection_id,
                style_id=style_id,
                output_format=output_format
            )

            logger.info(f"Style '{style_id}' requested for collection '{collection_id}' (format: {output_format})")

            return self._json_response(style_doc, content_type=content_type)

        except ValueError as e:
            logger.warning(f"Style not found or invalid format: {e}")
            return self._error_response(
                message=str(e),
                status_code=404,
                error_type="NotFound"
            )
        except Exception as e:
            logger.error(f"Error getting style: {e}")
            return self._error_response(
                message=f"Internal server error: {str(e)}",
                status_code=500,
                error_type="InternalServerError"
            )

    def _negotiate_format(self, accept_header: str) -> str:
        """Parse Accept header and return best matching format."""
        if "vnd.leaflet" in accept_header:
            return "leaflet"
        elif "vnd.mapbox" in accept_header:
            return "mapbox"
        elif "vnd.ogc.cartosym" in accept_header:
            return "cartosym"
        return "leaflet"  # default for web clients


# Update get_ogc_triggers() to include style triggers:

def get_ogc_triggers() -> List[Dict[str, Any]]:
    """
    Get list of OGC Features API trigger configurations for function_app.py.

    Updated 17 DEC 2025: Added OGC API Styles endpoints.
    """
    return [
        # ... existing triggers ...
        {
            'route': 'features',
            'methods': ['GET'],
            'handler': OGCLandingPageTrigger().handle
        },
        {
            'route': 'features/conformance',
            'methods': ['GET'],
            'handler': OGCConformanceTrigger().handle
        },
        {
            'route': 'features/collections',
            'methods': ['GET'],
            'handler': OGCCollectionsTrigger().handle
        },
        {
            'route': 'features/collections/{collection_id}',
            'methods': ['GET'],
            'handler': OGCCollectionTrigger().handle
        },
        {
            'route': 'features/collections/{collection_id}/items',
            'methods': ['GET'],
            'handler': OGCItemsTrigger().handle
        },
        {
            'route': 'features/collections/{collection_id}/items/{feature_id}',
            'methods': ['GET'],
            'handler': OGCItemTrigger().handle
        },
        # NEW: OGC API Styles (17 DEC 2025)
        {
            'route': 'features/collections/{collection_id}/styles',
            'methods': ['GET'],
            'handler': OGCStylesListTrigger().handle
        },
        {
            'route': 'features/collections/{collection_id}/styles/{style_id}',
            'methods': ['GET'],
            'handler': OGCStyleTrigger().handle
        }
    ]
```

---

### 6. Function App Registration (`function_app.py`)

Add after existing OGC Features routes:

```python
# ============================================================================
# OGC API - STYLES (17 DEC 2025)
# ============================================================================
# Extends OGC Features with style management
# GET /api/features/collections/{id}/styles        - List styles
# GET /api/features/collections/{id}/styles/{sid}  - Get style (multi-format)

_ogc_styles_list = _ogc_triggers[6]['handler']
_ogc_style = _ogc_triggers[7]['handler']


@app.route(route="features/collections/{collection_id}/styles", methods=["GET"])
def ogc_features_styles_list(req: func.HttpRequest) -> func.HttpResponse:
    """OGC Styles API: List styles for collection."""
    return _ogc_styles_list(req)


@app.route(route="features/collections/{collection_id}/styles/{style_id}", methods=["GET"])
def ogc_features_style(req: func.HttpRequest) -> func.HttpResponse:
    """OGC Styles API: Get style document (supports ?f=leaflet|mapbox|cartosym)."""
    return _ogc_style(req)
```

---

## CartoSym-JSON Examples

### Simple Static Style (Polygon)

```json
{
  "name": "protected-areas-default",
  "title": "Protected Areas",
  "description": "Default style for protected areas",
  "metadata": {
    "attribution": "IUCN/WDPA"
  },
  "stylingRules": [
    {
      "name": "default-polygon",
      "symbolizer": {
        "type": "Polygon",
        "fill": {
          "color": "#BAF2B3",
          "opacity": 0.7
        },
        "stroke": {
          "color": "#4C7300",
          "width": 1.5,
          "opacity": 1.0,
          "cap": "round",
          "join": "round"
        }
      }
    }
  ]
}
```

### Data-Driven Style (By Category)

```json
{
  "name": "iucn-by-category",
  "title": "IUCN Categories",
  "stylingRules": [
    {
      "name": "category-ia",
      "selector": {
        "op": "=",
        "args": [{"property": "iucn_cat"}, "Ia"]
      },
      "symbolizer": {
        "type": "Polygon",
        "fill": {"color": "#1a9850", "opacity": 0.7},
        "stroke": {"color": "#0d5c2e", "width": 1.5}
      }
    },
    {
      "name": "category-ib",
      "selector": {
        "op": "=",
        "args": [{"property": "iucn_cat"}, "Ib"]
      },
      "symbolizer": {
        "type": "Polygon",
        "fill": {"color": "#91cf60", "opacity": 0.7},
        "stroke": {"color": "#5a9c3a", "width": 1.5}
      }
    },
    {
      "name": "fallback",
      "symbolizer": {
        "type": "Polygon",
        "fill": {"color": "#cccccc", "opacity": 0.5},
        "stroke": {"color": "#999999", "width": 1}
      }
    }
  ]
}
```

---

## Client Usage Examples

### Leaflet (Static Style)

```javascript
async function loadStyledLayer(collectionId, styleId = 'default') {
  // Fetch features
  const geojson = await fetch(`/api/features/collections/${collectionId}/items`).then(r => r.json());

  // Fetch Leaflet-ready style
  const style = await fetch(`/api/features/collections/${collectionId}/styles/${styleId}?f=leaflet`).then(r => r.json());

  // Apply to map
  if (style.type === 'data-driven') {
    // Use the generated style function
    const styleFunc = new Function('return ' + style.styleFunction)();
    L.geoJSON(geojson, { style: styleFunc }).addTo(map);
  } else {
    // Simple static style
    L.geoJSON(geojson, { style }).addTo(map);
  }
}
```

### MapLibre GL / Mapbox GL

```javascript
async function loadMapboxStyle(collectionId, styleId = 'default') {
  const styleSpec = await fetch(`/api/features/collections/${collectionId}/styles/${styleId}?f=mapbox`).then(r => r.json());

  // Add source
  map.addSource(collectionId, {
    type: 'geojson',
    data: `/api/features/collections/${collectionId}/items`
  });

  // Add each layer from the style
  for (const layer of styleSpec.layers) {
    map.addLayer({
      ...layer,
      source: collectionId
    });
  }
}
```

---

## ETL Integration

Auto-create default styles when processing vectors. Add to `process_vector` Stage 2 completion:

```python
# In services/vector/postgis_handler.py or similar
def create_vector_table_with_style(table_name: str, geometry_type: str, ...):
    """Create PostGIS table and auto-generate default style."""
    # ... existing table creation logic ...

    # Auto-create default style
    from ogc_features.repository import OGCFeaturesRepository
    repo = OGCFeaturesRepository()
    repo.create_default_style_for_collection(
        collection_id=table_name,
        geometry_type=geometry_type
    )
```

---

## Testing

### API Endpoints

```bash
# List styles for a collection
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/features/collections/countries/styles

# Get style in Leaflet format (default)
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/features/collections/countries/styles/default?f=leaflet"

# Get style in Mapbox format
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/features/collections/countries/styles/default?f=mapbox"

# Get canonical CartoSym-JSON
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/features/collections/countries/styles/default?f=cartosym"
```

---

## Implementation Checklist

1. [ ] Add Pydantic models to `ogc_features/models.py`
2. [ ] Create `ogc_features/style_translator.py`
3. [ ] Add repository methods to `ogc_features/repository.py`
4. [ ] Add service methods to `ogc_features/service.py`
5. [ ] Add trigger classes to `ogc_features/triggers.py`
6. [ ] Update `get_ogc_triggers()` to include style triggers
7. [ ] Add schema to `core/schema/sql_generator.py`
8. [ ] Register routes in `function_app.py`
9. [ ] Deploy and run full-rebuild
10. [ ] Test endpoints
11. [ ] (Optional) Add ETL integration for auto-generated default styles

---

## Future Enhancements

1. **Style CRUD operations** - POST/PUT/DELETE for style management
2. **Style validation** - Validate CartoSym-JSON against schema before storage
3. **OpenLayers output format** - Add `?f=openlayers` translator
4. **Scale-dependent styling** - Add minScale/maxScale to styling rules
5. **Sprite/icon support** - Handle marker images and sprites
6. **Style inheritance** - Allow styles to extend/override other styles
