# Plan: Promote UI with OGC Style Builder

**Created**: 26 DEC 2025
**Status**: PROPOSED
**Epic**: E12 - Interface Modernization
**Feature**: Promote Dashboard with Style Integration

---

## Overview

Create a web interface for promoting datasets with integrated OGC Style creation. Users can:
1. Select a STAC collection/item to promote
2. Set custom title, description, tags
3. Configure gallery settings
4. **NEW: Build and preview a basic style**
5. Save both promotion and style atomically

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    PROMOTE UI INTERFACE                         │
│  /api/interface/promote                                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────────┐  ┌──────────────────────────────────┐│
│  │  STAC SELECTOR       │  │  STYLE BUILDER                   ││
│  │  ────────────────    │  │  ──────────────                  ││
│  │  • Collections list  │  │  • Color picker (fill/stroke)    ││
│  │  • Items within      │  │  • Opacity slider                ││
│  │  • Search/filter     │  │  • Stroke width                  ││
│  │  • Preview metadata  │  │  • Data-driven option            ││
│  └──────────────────────┘  │  • Live preview on map           ││
│                             └──────────────────────────────────┘│
│  ┌──────────────────────┐  ┌──────────────────────────────────┐│
│  │  PROMOTION FORM      │  │  MAP PREVIEW                     ││
│  │  ────────────────    │  │  ──────────────                  ││
│  │  • promoted_id       │  │  • Leaflet map                   ││
│  │  • title (override)  │  │  • Sample features rendered      ││
│  │  • description       │  │  • Style applied live            ││
│  │  • tags[]            │  │  • Zoom to bbox                  ││
│  │  • classification    │  │                                  ││
│  │  • gallery toggle    │  │                                  ││
│  │  • gallery_order     │  │                                  ││
│  └──────────────────────┘  └──────────────────────────────────┘│
│                                                                  │
│  ┌──────────────────────────────────────────────────────────────┤
│  │  [Cancel]                              [Preview] [Promote]  ││
│  └──────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

---

## Stories

### S1: Basic Promote Interface (Foundation)
**Estimate**: 1 day

Create `/api/interface/promote` with:
- STAC collection/item selector (dropdown populated from STAC API)
- Promotion form fields (promoted_id, title, description, tags, classification)
- Gallery toggle with order input
- Form validation
- Submit to `POST /api/promote`

**Files**:
- `web_interfaces/promote/__init__.py`
- `web_interfaces/promote/interface.py`

### S2: Style Builder Component
**Estimate**: 1 day

Add style builder panel with:
- Geometry type detection (from STAC item properties or first feature)
- **Polygon styles**: Fill color, fill opacity, stroke color, stroke width
- **Line styles**: Stroke color, stroke width, dash pattern
- **Point styles**: Marker color, marker size, marker shape
- Color picker (HTML5 native or simple palette)
- Opacity slider (0-100%)
- Generate CartoSym-JSON from selections

**Files**:
- `web_interfaces/promote/style_builder.py` (component)

### S3: Live Map Preview
**Estimate**: 0.5 day

Add Leaflet map showing:
- Sample features from selected collection (via OGC Features API)
- Style applied in real-time as user adjusts
- Bbox zoom from STAC metadata
- Toggle between styled/unstyled view

**Integration**:
- Fetch sample: `GET /api/features/collections/{id}/items?limit=100`
- Apply style via StyleTranslator.to_leaflet()

### S4: Backend Integration - Save Style with Promote
**Estimate**: 0.5 day

Wire up the workflow:
1. On promote submit, if style defined:
   - Create style via `OGCStylesRepository.create_style()`
   - Set `style_id` in promotion payload
2. Atomic operation (transaction)
3. Return both promoted_id and style_id in response

**Files**:
- `services/promote_service.py` - Add `promote_with_style()` method
- `triggers/promote.py` - Accept `style_spec` in POST body

### S5: Existing Styles Integration
**Estimate**: 0.5 day

Allow selecting existing style instead of building new:
- Dropdown: "Create new style" or select from existing
- List existing styles: `GET /api/features/collections/{id}/styles`
- Preview existing style on map
- Option to clone and modify existing style

### S6: Data-Driven Styling (Advanced)
**Estimate**: 1 day (optional, Phase 2)

For categorical data:
- Detect string/enum properties in schema
- Auto-generate rules per unique value
- Color palette picker (categorical, sequential, diverging)
- Property selector dropdown

---

## Database Changes

**None required!** The `style_id` column already exists in `app.promoted_datasets`.

---

## API Changes

### Enhanced POST /api/promote

```json
{
  "promoted_id": "my-dataset",
  "stac_collection_id": "roads-network",
  "title": "Road Network",
  "description": "Global road infrastructure",
  "tags": ["infrastructure", "transport"],
  "classification": "public",
  "gallery": true,
  "gallery_order": 5,

  // NEW: Inline style definition
  "style": {
    "title": "Default Road Style",
    "spec": {
      "version": "1.0",
      "name": "road-style",
      "rules": [{
        "symbolizers": [{
          "type": "stroke",
          "stroke": "#FF6B00",
          "strokeWidth": 2,
          "strokeOpacity": 0.8
        }]
      }]
    }
  }
}
```

**Response** (enhanced):
```json
{
  "promoted_id": "my-dataset",
  "style_id": "my-dataset-default",
  "style_url": "/api/features/collections/roads-network/styles/my-dataset-default",
  "viewer_url": "/api/vector/viewer?collection=roads-network&style=my-dataset-default"
}
```

---

## UI Flow

```
1. User navigates to /api/interface/promote

2. STAC Selection
   └─> User selects collection from dropdown
   └─> System detects geometry type
   └─> Map shows sample features (unstyled)

3. Style Builder
   └─> Appropriate controls shown (polygon/line/point)
   └─> User picks colors, opacity, widths
   └─> Map updates live with style preview

4. Promotion Form
   └─> User fills promoted_id, title, description
   └─> Selects tags from suggestions + custom
   └─> Sets classification (public/ouo)
   └─> Toggles gallery + sets order

5. Submit
   └─> POST /api/promote with style spec
   └─> Backend creates style + promotion atomically
   └─> Success shows links: Gallery, Viewer, OGC Styles
```

---

## Style Builder Component Detail

### Polygon Style Controls
```
┌─────────────────────────────────────┐
│ Fill Color     [#3388ff] [picker]  │
│ Fill Opacity   [====●====] 50%     │
│ Stroke Color   [#2255bb] [picker]  │
│ Stroke Width   [==●======] 2px     │
│ Stroke Opacity [======●==] 80%     │
└─────────────────────────────────────┘
```

### Line Style Controls
```
┌─────────────────────────────────────┐
│ Stroke Color   [#FF6B00] [picker]  │
│ Stroke Width   [====●====] 3px     │
│ Stroke Opacity [========●] 100%    │
│ Dash Pattern   [solid ▼]           │
└─────────────────────────────────────┘
```

### Point Style Controls
```
┌─────────────────────────────────────┐
│ Marker Color   [#E74C3C] [picker]  │
│ Marker Size    [==●======] 8px     │
│ Stroke Color   [#FFFFFF] [picker]  │
│ Stroke Width   [●========] 1px     │
└─────────────────────────────────────┘
```

---

## CartoSym-JSON Generation

From UI inputs, generate:

```javascript
function buildCartoSymStyle(inputs) {
  const symbolizer = {
    type: inputs.geometryType === 'point' ? 'marker' :
          inputs.geometryType === 'line' ? 'stroke' : 'fill'
  };

  if (inputs.geometryType === 'polygon') {
    symbolizer.fill = inputs.fillColor;
    symbolizer.fillOpacity = inputs.fillOpacity;
    symbolizer.stroke = inputs.strokeColor;
    symbolizer.strokeWidth = inputs.strokeWidth;
    symbolizer.strokeOpacity = inputs.strokeOpacity;
  } else if (inputs.geometryType === 'line') {
    symbolizer.stroke = inputs.strokeColor;
    symbolizer.strokeWidth = inputs.strokeWidth;
    symbolizer.strokeOpacity = inputs.strokeOpacity;
  } else { // point
    symbolizer.fill = inputs.markerColor;
    symbolizer.radius = inputs.markerSize;
    symbolizer.stroke = inputs.strokeColor;
    symbolizer.strokeWidth = inputs.strokeWidth;
  }

  return {
    version: "1.0",
    name: inputs.styleName,
    rules: [{ symbolizers: [symbolizer] }]
  };
}
```

---

## Dependencies

- Leaflet JS (already in base template)
- HTML5 color picker (native, no library needed)
- Existing OGC Styles infrastructure
- Existing Promote API

---

## Acceptance Criteria

1. [ ] User can select STAC collection/item from dropdown
2. [ ] Style builder shows appropriate controls for geometry type
3. [ ] Live map preview updates as style changes
4. [ ] Form validates required fields
5. [ ] Submit creates both style and promotion
6. [ ] Success shows viewer URL with style applied
7. [ ] Existing styles can be selected instead of creating new

---

## Future Enhancements (Phase 2+)

- **Data-driven styling**: Color by property value
- **Style templates**: Pre-built styles for common use cases
- **Import/export**: Upload CartoSym-JSON files
- **Style versioning**: Track style changes over time
- **Batch promote**: Promote multiple items with shared style
