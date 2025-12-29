# ============================================================================
# CLAUDE CONTEXT - STYLE TRANSLATOR SERVICE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Service - CartoSym-JSON to client format translation
# PURPOSE: Convert OGC CartoSym-JSON to Leaflet/Mapbox GL formats
# LAST_REVIEWED: 18 DEC 2025
# EXPORTS: StyleTranslator
# DEPENDENCIES: Standard library only
# ============================================================================
"""
OGC API Styles Translator Service.

Translates CartoSym-JSON to various output formats:
- Leaflet (static and data-driven styles)
- Mapbox GL (layer definitions)

CartoSym-JSON is the OGC-native canonical format stored in the database.

Usage:
    translator = StyleTranslator(cartosym_dict)
    leaflet_style = translator.to_leaflet()
    mapbox_style = translator.to_mapbox()

Created: 18 DEC 2025
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
        """Find first rule matching geometry type."""
        for rule in self.rules:
            # Check geometryType (CartoSym-JSON standard) or symbolizer.type (legacy)
            if rule.get("geometryType") == sym_type:
                return rule
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
        Source must be added client-side.
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
