# OGC API Styles Implementation Guide

## Azure Functions Python V2

This guide describes how to implement OGC API Styles endpoints that store styles in CartoSym-JSON format and serve multiple output encodings (Leaflet, Mapbox GL, etc.) on demand.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  PostgreSQL                                                 │
│  ┌──────────────────────┐    ┌───────────────────────────┐  │
│  │ feature tables       │    │ feature_collection_styles │  │
│  │ (PostGIS geometry)   │    │ (CartoSym-JSON source)    │  │
│  └──────────────────────┘    └───────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                │                          │
                ▼                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Azure Function App (OGC API)                               │
│                                                             │
│  GET /collections/{id}/items          → GeoJSON features    │
│  GET /collections/{id}/styles         → list styles         │
│  GET /collections/{id}/styles/{sid}   → style document      │
│       Accept: application/vnd.ogc.cartosym+json             │
│       ?f=cartosym  → CartoSym-JSON (canonical)              │
│       ?f=leaflet   → Leaflet style object/function          │
│       ?f=mapbox    → Mapbox GL style layers                 │
└─────────────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────┐
│  Client Applications                                        │
│  - Leaflet web maps                                         │
│  - MapLibre GL / Mapbox GL                                  │
│  - OpenLayers                                               │
│  - Custom applications                                      │
└─────────────────────────────────────────────────────────────┘
```

---

## Database Schema

### Styles Table

```sql
CREATE TABLE feature_collection_styles (
    id SERIAL PRIMARY KEY,
    collection_id TEXT NOT NULL,           -- matches OGC Features collection
    style_id TEXT NOT NULL,                -- url-safe identifier
    title TEXT,
    description TEXT,
    style_spec JSONB NOT NULL,             -- CartoSym-JSON document
    is_default BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(collection_id, style_id)
);

-- Index for fast lookups
CREATE INDEX idx_styles_collection ON feature_collection_styles(collection_id);

-- Ensure only one default per collection
CREATE UNIQUE INDEX idx_styles_default 
ON feature_collection_styles(collection_id) 
WHERE is_default = true;
```

---

## CartoSym-JSON Structure

### Canonical Storage Format

This is the OGC-native format stored in the database:

```json
{
  "name": "iucn-categories-i-ii",
  "title": "IUCN Categories I-II",
  "description": "Protected areas from WDPA",
  "metadata": {
    "attribution": "IUCN/IBAT",
    "version": "1.0.0"
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

### Data-Driven Styling with Selectors

Use CQL2-JSON expressions for conditional styling:

```json
{
  "name": "iucn-by-category",
  "title": "IUCN Categories Styled",
  "stylingRules": [
    {
      "name": "category-ia",
      "selector": {
        "op": "=",
        "args": [{ "property": "iucn_cat" }, "Ia"]
      },
      "symbolizer": {
        "type": "Polygon",
        "fill": { "color": "#1a9850", "opacity": 0.7 },
        "stroke": { "color": "#0d5c2e", "width": 1.5 }
      }
    },
    {
      "name": "category-ib",
      "selector": {
        "op": "=",
        "args": [{ "property": "iucn_cat" }, "Ib"]
      },
      "symbolizer": {
        "type": "Polygon",
        "fill": { "color": "#91cf60", "opacity": 0.7 },
        "stroke": { "color": "#5a9c3a", "width": 1.5 }
      }
    },
    {
      "name": "category-ii",
      "selector": {
        "op": "=",
        "args": [{ "property": "iucn_cat" }, "II"]
      },
      "symbolizer": {
        "type": "Polygon",
        "fill": { "color": "#d9ef8b", "opacity": 0.7 },
        "stroke": { "color": "#a3c263", "width": 1.5 }
      }
    },
    {
      "name": "fallback",
      "symbolizer": {
        "type": "Polygon",
        "fill": { "color": "#cccccc", "opacity": 0.5 },
        "stroke": { "color": "#999999", "width": 1 }
      }
    }
  ]
}
```

---

## Azure Functions Implementation

### Project Structure

```
ogc-api/
├── function_app.py
├── routers/
│   ├── __init__.py
│   ├── collections.py
│   ├── features.py
│   └── styles.py
├── services/
│   ├── __init__.py
│   ├── database.py
│   └── style_translator.py
├── models/
│   ├── __init__.py
│   └── styles.py
├── requirements.txt
└── host.json
```

### Main Function App Entry Point

```python
# function_app.py
import azure.functions as func
from routers import styles, features, collections

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# Register style routes
app.register_functions(styles.bp)
app.register_functions(features.bp)
app.register_functions(collections.bp)
```

### Styles Router

```python
# routers/styles.py
import azure.functions as func
import json
from services.database import get_db_connection
from services.style_translator import StyleTranslator

bp = func.Blueprint()

CONTENT_TYPES = {
    "cartosym": "application/vnd.ogc.cartosym+json",
    "leaflet": "application/vnd.leaflet.style+json",
    "mapbox": "application/vnd.mapbox.style+json",
    "json": "application/json"
}


@bp.route(route="collections/{collection_id}/styles", methods=["GET"])
async def list_styles(req: func.HttpRequest) -> func.HttpResponse:
    """
    GET /collections/{collection_id}/styles
    
    Returns list of available styles for a collection.
    OGC API - Styles conformance: /req/core/styles-list
    """
    collection_id = req.route_params.get("collection_id")
    
    async with get_db_connection() as conn:
        rows = await conn.fetch("""
            SELECT style_id, title, description, is_default
            FROM feature_collection_styles
            WHERE collection_id = $1
            ORDER BY is_default DESC, title ASC
        """, collection_id)
    
    base_url = req.url.split("?")[0]
    
    styles = []
    for row in rows:
        style_entry = {
            "id": row["style_id"],
            "title": row["title"],
            "description": row["description"],
            "default": row["is_default"],
            "links": [
                {
                    "rel": "describedby",
                    "href": f"{base_url}/{row['style_id']}",
                    "type": "application/vnd.ogc.cartosym+json",
                    "title": "CartoSym-JSON (canonical)"
                },
                {
                    "rel": "describedby",
                    "href": f"{base_url}/{row['style_id']}?f=leaflet",
                    "type": "application/vnd.leaflet.style+json",
                    "title": "Leaflet style"
                },
                {
                    "rel": "describedby", 
                    "href": f"{base_url}/{row['style_id']}?f=mapbox",
                    "type": "application/vnd.mapbox.style+json",
                    "title": "Mapbox GL style"
                }
            ]
        }
        styles.append(style_entry)
    
    response_body = {
        "styles": styles,
        "links": [
            {
                "rel": "self",
                "href": base_url,
                "type": "application/json"
            }
        ]
    }
    
    return func.HttpResponse(
        json.dumps(response_body, indent=2),
        status_code=200,
        mimetype="application/json"
    )


@bp.route(route="collections/{collection_id}/styles/{style_id}", methods=["GET"])
async def get_style(req: func.HttpRequest) -> func.HttpResponse:
    """
    GET /collections/{collection_id}/styles/{style_id}
    
    Returns a style document in the requested format.
    Supports content negotiation via Accept header or ?f= query param.
    
    OGC API - Styles conformance: /req/core/style
    """
    collection_id = req.route_params.get("collection_id")
    style_id = req.route_params.get("style_id")
    
    # Determine output format (query param takes precedence)
    output_format = req.params.get("f", "").lower()
    if not output_format:
        output_format = _negotiate_format(req.headers.get("Accept", ""))
    
    # Fetch canonical CartoSym-JSON from database
    async with get_db_connection() as conn:
        row = await conn.fetchrow("""
            SELECT style_spec, title, description
            FROM feature_collection_styles
            WHERE collection_id = $1 AND style_id = $2
        """, collection_id, style_id)
    
    if not row:
        return func.HttpResponse(
            json.dumps({"error": "Style not found"}),
            status_code=404,
            mimetype="application/json"
        )
    
    cartosym = row["style_spec"]
    translator = StyleTranslator(cartosym)
    
    # Translate to requested format
    if output_format in ("leaflet", ""):
        result = translator.to_leaflet()
        content_type = CONTENT_TYPES["leaflet"]
    elif output_format == "mapbox":
        result = translator.to_mapbox()
        content_type = CONTENT_TYPES["mapbox"]
    elif output_format == "cartosym":
        result = cartosym
        content_type = CONTENT_TYPES["cartosym"]
    else:
        return func.HttpResponse(
            json.dumps({"error": f"Unsupported format: {output_format}"}),
            status_code=400,
            mimetype="application/json"
        )
    
    return func.HttpResponse(
        json.dumps(result, indent=2),
        status_code=200,
        mimetype=content_type
    )


def _negotiate_format(accept_header: str) -> str:
    """Parse Accept header and return best matching format."""
    if "vnd.leaflet" in accept_header:
        return "leaflet"
    elif "vnd.mapbox" in accept_header:
        return "mapbox"
    elif "vnd.ogc.cartosym" in accept_header:
        return "cartosym"
    return "leaflet"  # default for web clients
```

### Style Translator Service

```python
# services/style_translator.py
from typing import Any, Optional
import re


class StyleTranslator:
    """
    Translates CartoSym-JSON to various output formats.
    """
    
    def __init__(self, cartosym: dict):
        self.cartosym = cartosym
        self.rules = cartosym.get("stylingRules", [])
    
    def to_leaflet(self) -> dict:
        """
        Convert CartoSym-JSON to Leaflet-compatible format.
        
        Returns either:
        - A static style object (if no selectors)
        - A style specification with rules (if data-driven)
        """
        has_selectors = any(rule.get("selector") for rule in self.rules)
        
        if has_selectors:
            return self._to_leaflet_rules()
        else:
            return self._to_leaflet_static()
    
    def _to_leaflet_static(self) -> dict:
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
        
        # Remove None values
        return {k: v for k, v in style.items() if v is not None}
    
    def _to_leaflet_rules(self) -> dict:
        """
        Convert data-driven style to Leaflet rules format.
        
        Returns a structure that can be used to generate a style function:
        {
            "type": "data-driven",
            "property": "iucn_cat",
            "rules": [
                {"value": "Ia", "style": {...}},
                {"value": "Ib", "style": {...}}
            ],
            "default": {...}
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
    
    def _symbolizer_to_leaflet(self, symbolizer: dict) -> dict:
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
    
    def _parse_selector(self, selector: dict) -> tuple[Optional[str], Any]:
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
        property_name: str, 
        rules: list, 
        default: dict
    ) -> str:
        """
        Generate JavaScript code for a Leaflet style function.
        
        This can be eval'd client-side or used as reference.
        """
        conditions = []
        for rule in rules:
            value = rule["value"]
            style_json = self._to_js_object(rule["style"])
            if isinstance(value, str):
                conditions.append(f'  if (props.{property_name} === "{value}") return {style_json};')
            else:
                conditions.append(f'  if (props.{property_name} === {value}) return {style_json};')
        
        default_json = self._to_js_object(default or {})
        
        return f"""function(feature) {{
  const props = feature.properties || {{}};
{chr(10).join(conditions)}
  return {default_json};
}}"""
    
    def _to_js_object(self, d: dict) -> str:
        """Convert Python dict to JavaScript object literal string."""
        import json
        return json.dumps(d)
    
    def _find_rule_by_type(self, sym_type: str) -> Optional[dict]:
        """Find first rule matching symbolizer type."""
        for rule in self.rules:
            if rule.get("symbolizer", {}).get("type") == sym_type:
                return rule
        return None
    
    def to_mapbox(self) -> dict:
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
    
    def _selector_to_mapbox_filter(self, selector: dict) -> list:
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

### Database Connection Service

```python
# services/database.py
import os
import asyncpg
from contextlib import asynccontextmanager

DATABASE_URL = os.environ.get("DATABASE_URL")


@asynccontextmanager
async def get_db_connection():
    """
    Async context manager for database connections.
    
    Usage:
        async with get_db_connection() as conn:
            result = await conn.fetch("SELECT ...")
    """
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        await conn.close()


# Connection pool for production use
_pool = None

async def get_pool():
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=2,
            max_size=10
        )
    return _pool


@asynccontextmanager  
async def get_pooled_connection():
    """Use connection pool for better performance."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn
```

---

## Client Usage Examples

### Leaflet (Static Style)

```javascript
// Fetch style and apply to GeoJSON layer
async function loadStyledLayer(collectionId, styleId = 'default') {
  // Fetch features
  const featuresRes = await fetch(`/collections/${collectionId}/items`);
  const geojson = await featuresRes.json();
  
  // Fetch Leaflet-ready style
  const styleRes = await fetch(`/collections/${collectionId}/styles/${styleId}?f=leaflet`);
  const style = await styleRes.json();
  
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

### Leaflet (Data-Driven Style)

```javascript
// For data-driven styles, the API returns a structure you can use
// to build a style function client-side

async function loadDataDrivenLayer(collectionId) {
  const styleRes = await fetch(`/collections/${collectionId}/styles/by-category?f=leaflet`);
  const styleSpec = await styleRes.json();
  
  // styleSpec looks like:
  // {
  //   "type": "data-driven",
  //   "property": "iucn_cat",
  //   "rules": [
  //     {"value": "Ia", "style": {"fillColor": "#1a9850", ...}},
  //     {"value": "Ib", "style": {"fillColor": "#91cf60", ...}}
  //   ],
  //   "default": {"fillColor": "#cccccc", ...},
  //   "styleFunction": "function(feature) { ... }"
  // }
  
  // Option 1: Use pre-generated function string
  const styleFunc = new Function('return ' + styleSpec.styleFunction)();
  
  // Option 2: Build your own from rules
  const styleFunc2 = (feature) => {
    const value = feature.properties[styleSpec.property];
    const match = styleSpec.rules.find(r => r.value === value);
    return match ? match.style : styleSpec.default;
  };
  
  const geojson = await fetch(`/collections/${collectionId}/items`).then(r => r.json());
  L.geoJSON(geojson, { style: styleFunc }).addTo(map);
}
```

### MapLibre GL / Mapbox GL

```javascript
async function loadMapboxStyle(collectionId, styleId = 'default') {
  const styleRes = await fetch(`/collections/${collectionId}/styles/${styleId}?f=mapbox`);
  const styleSpec = await styleRes.json();
  
  // styleSpec contains Mapbox GL layers array
  // Add source and layers to existing map
  
  map.addSource(collectionId, {
    type: 'geojson',
    data: `/collections/${collectionId}/items`
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

## OGC API Styles Conformance

### Endpoints Implemented

| Endpoint | Conformance Class | Description |
|----------|------------------|-------------|
| `GET /collections/{id}/styles` | `/req/core/styles-list` | List available styles |
| `GET /collections/{id}/styles/{styleId}` | `/req/core/style` | Get style document |

### Content Negotiation

The API supports format selection via:

1. **Query parameter** (takes precedence): `?f=leaflet`, `?f=mapbox`, `?f=cartosym`
2. **Accept header**: `Accept: application/vnd.leaflet.style+json`

### Media Types

| Format | Media Type |
|--------|-----------|
| CartoSym-JSON | `application/vnd.ogc.cartosym+json` |
| Leaflet | `application/vnd.leaflet.style+json` |
| Mapbox GL | `application/vnd.mapbox.style+json` |

---

## ETL Pipeline Integration

When your geospatial ETL creates a new feature collection, it should also create a default style:

```python
async def create_collection_with_style(
    collection_id: str,
    geometry_type: str,  # 'Polygon', 'Line', 'Point'
    default_colors: dict = None
):
    """
    Create a feature collection and its default style.
    Called from ETL pipeline after table creation.
    """
    colors = default_colors or {
        "fill": "#3388ff",
        "stroke": "#2266cc"
    }
    
    # Generate default CartoSym-JSON based on geometry type
    if geometry_type == "Polygon":
        style_spec = {
            "name": f"{collection_id}-default",
            "title": f"Default style for {collection_id}",
            "stylingRules": [{
                "name": "default",
                "symbolizer": {
                    "type": "Polygon",
                    "fill": {"color": colors["fill"], "opacity": 0.6},
                    "stroke": {"color": colors["stroke"], "width": 1.5}
                }
            }]
        }
    elif geometry_type == "Line":
        style_spec = {
            "name": f"{collection_id}-default",
            "title": f"Default style for {collection_id}",
            "stylingRules": [{
                "name": "default",
                "symbolizer": {
                    "type": "Line",
                    "stroke": {"color": colors["stroke"], "width": 2}
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
                        "fill": {"color": colors["fill"]},
                        "stroke": {"color": colors["stroke"], "width": 1}
                    }
                }
            }]
        }
    
    async with get_db_connection() as conn:
        await conn.execute("""
            INSERT INTO feature_collection_styles 
            (collection_id, style_id, title, style_spec, is_default)
            VALUES ($1, 'default', $2, $3, true)
            ON CONFLICT (collection_id, style_id) DO UPDATE
            SET style_spec = $3, updated_at = now()
        """, collection_id, style_spec["title"], json.dumps(style_spec))
```

---

## Future Enhancements

1. **Style CRUD operations** - POST/PUT/DELETE for style management
2. **Style validation** - Validate CartoSym-JSON against schema before storage
3. **OpenLayers output format** - Add `?f=openlayers` translator
4. **Scale-dependent styling** - Add minScale/maxScale to styling rules
5. **Sprite/icon support** - Handle marker images and sprites
6. **Style inheritance** - Allow styles to extend/override other styles