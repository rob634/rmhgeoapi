# TiTiler Consumer Documentation - Implementation Plan

**Date**: 16 JAN 2026
**For**: TiTiler Claude (rmhtitiler app)
**From**: ETL Claude (rmhgeoapi app)
**Status**: Handoff Document - Ready for Implementation

---

## Overview

This document provides the implementation plan for consumer-facing documentation on the TiTiler app (`rmhtitiler`). The goal is to create narrative documentation that serves two distinct audiences accessing the same API endpoints.

**Key Principle**: Keep documentation separate from ETL docs — different audiences, different auth stories, different security boundaries.

---

## Target Audiences

### Track A: Web Developers (Internal Team)

**Primary goal**: Replace ArcGIS/GEE workflows with standards-based alternatives

**Mental model**: "I have a web app that needs maps and spatial data"

**Key messages**:
- 30-100x cost savings vs ArcGIS/GEE
- Standards-based = portable skills, no vendor lock-in
- MapLibre GL JS (30kb) vs ArcGIS JS SDK (800kb)

### Track B: Data Scientists (External Clients)

**Primary goal**: Access and analyze data without downloading entire datasets

**Mental model**: "I have a notebook and need to query geospatial data"

**Key messages**:
- Compute goes to data (no more downloading 50GB files)
- HTTP range requests = read only what you need
- Same file serves tiles, point queries, and windowed analysis

---

## Recommended Tech Stack

**Documentation Framework**: MkDocs with Material theme

**Why MkDocs Material**:
- Python-based (matches your stack)
- Excellent code syntax highlighting
- Built-in search
- Easy deployment alongside FastAPI
- Clean, professional appearance

**Alternative**: Docusaurus (React-based, more features, heavier)

---

## Site Structure

```
rmhtitiler/
├── docs/
│   ├── index.md                    # Landing page with audience selector
│   ├── guide/
│   │   ├── webdev/                 # Track A: Web Developers
│   │   │   ├── index.md            # Why migrate from ArcGIS/GEE
│   │   │   ├── concept-mapping.md  # ArcGIS → Standards translation table
│   │   │   ├── quick-start.md      # Tiles in 5 minutes (MapLibre)
│   │   │   └── recipes/            # Common use cases
│   │   │       ├── replace-feature-service.md
│   │   │       ├── display-raster.md
│   │   │       └── spatial-query.md
│   │   ├── analysis/               # Track B: Data Scientists
│   │   │   ├── index.md            # Cloud-native analysis philosophy
│   │   │   ├── quick-start.md      # Query data in 5 minutes
│   │   │   ├── point-queries.md    # FATHOM-style point extraction
│   │   │   ├── windowed-reads.md   # COG partial reads with rasterio
│   │   │   └── stac-search.md      # pystac-client examples
│   │   └── auth/                   # Shared: Authentication
│   │       └── browser-to-notebook.md  # Token transfer workflow
│   ├── case-studies/
│   │   └── fathom-flood-data.md    # The "killer demo"
│   └── reference/                  # Links to auto-generated API docs
│       └── index.md                # Points to /docs and /redoc
├── mkdocs.yml                      # MkDocs configuration
└── requirements-docs.txt           # mkdocs-material, etc.
```

---

## Content Outlines

### Landing Page (index.md)

```markdown
# Geospatial APIs Documentation

Welcome to the Geospatial APIs platform.

## Choose Your Path

<div class="grid cards">
  <a href="guide/webdev/">
    <h3>Web Developers</h3>
    <p>Building maps? Replacing ArcGIS? Start here.</p>
  </a>
  <a href="guide/analysis/">
    <h3>Data Scientists</h3>
    <p>Analyzing geospatial data from notebooks? Start here.</p>
  </a>
</div>

## Quick Links

- [API Reference (Swagger)](/docs)
- [API Reference (ReDoc)](/redoc)
- [FATHOM Flood Data Case Study](case-studies/fathom-flood-data.md)
```

---

### Web Developer Guide: Concept Mapping (concept-mapping.md)

```markdown
# Concept Mapping: ArcGIS/GEE to Standards

| You're used to...              | Here it's...                     |
|--------------------------------|----------------------------------|
| ArcGIS Feature Service         | TiPG `/collections/{id}/items`   |
| ArcGIS Map Service tiles       | TiTiler `/cog/tiles/{z}/{x}/{y}` |
| Portal item search             | STAC catalog `/search`           |
| ArcGIS JS SDK (800kb)          | MapLibre GL JS (30kb)            |
| GEE ImageCollection            | STAC collection + COG access     |
| esriGeometryPolygon            | GeoJSON (actual standard)        |
| Layer.queryFeatures()          | OGC API Features + CQL filters   |
| ImageServer.identify()         | TiTiler `/point/{lon},{lat}`     |

## Why This Matters

- **Portability**: Standards work everywhere, not just one vendor
- **Cost**: No per-seat licensing, no usage tiers
- **Performance**: Purpose-built tools outperform general platforms
- **Skills**: Learn once, use anywhere
```

---

### Web Developer Guide: Quick Start (quick-start.md)

```markdown
# Quick Start: Tiles in 5 Minutes

## 1. Install MapLibre GL JS

```html
<link href="https://unpkg.com/maplibre-gl/dist/maplibre-gl.css" rel="stylesheet" />
<script src="https://unpkg.com/maplibre-gl/dist/maplibre-gl.js"></script>
```

## 2. Display a Raster Layer

```javascript
const map = new maplibregl.Map({
  container: 'map',
  style: {
    version: 8,
    sources: {
      'fathom': {
        type: 'raster',
        tiles: [
          'https://rmhtitiler.../cog/tiles/{z}/{x}/{y}?url=...'
        ],
        tileSize: 256
      }
    },
    layers: [{
      id: 'fathom-layer',
      type: 'raster',
      source: 'fathom'
    }]
  },
  center: [29.8, -2.0],  // Rwanda
  zoom: 8
});
```

## 3. Add Vector Features

```javascript
map.addSource('admin-boundaries', {
  type: 'vector',
  tiles: ['https://rmhtitiler.../collections/admin0/tiles/{z}/{x}/{y}']
});

map.addLayer({
  id: 'admin-fill',
  type: 'fill',
  source: 'admin-boundaries',
  'source-layer': 'default',
  paint: {
    'fill-color': '#088',
    'fill-opacity': 0.5
  }
});
```

## Next Steps

- [Replace a Feature Service](recipes/replace-feature-service.md)
- [Display Raster Imagery](recipes/display-raster.md)
- [Spatial Queries](recipes/spatial-query.md)
```

---

### Data Scientist Guide: Point Queries (point-queries.md)

```markdown
# Point Queries: Get Values at Coordinates

The most common analysis pattern: "What's the flood depth at this location?"

## Python Example

```python
import requests

# Query flood depth at a point in Rwanda
response = requests.get(
    "https://rmhtitiler.../cog/point/-1.9403,29.8739",
    params={
        "url": "https://storage.../fathom/rwanda_flood_depth.tif"
    },
    headers={"Authorization": f"Bearer {token}"}
)

data = response.json()
print(f"Flood depth: {data['values'][0]} meters")
```

## Batch Queries

For multiple points, use a loop or async requests:

```python
import asyncio
import aiohttp

async def query_point(session, lon, lat, url):
    async with session.get(
        f"https://rmhtitiler.../cog/point/{lon},{lat}",
        params={"url": url}
    ) as resp:
        return await resp.json()

async def query_many_points(points, cog_url):
    async with aiohttp.ClientSession() as session:
        tasks = [query_point(session, p[0], p[1], cog_url) for p in points]
        return await asyncio.gather(*tasks)

# Query 100 points
points = [(29.8 + i*0.01, -2.0 + i*0.01) for i in range(100)]
results = asyncio.run(query_many_points(points, cog_url))
```

## Response Format

```json
{
  "coordinates": [-1.9403, 29.8739],
  "values": [2.5],
  "band_names": ["flood_depth"]
}
```
```

---

### Auth Flow Guide (browser-to-notebook.md)

```markdown
# Using Your Browser Token in a Notebook

## Why This Works

The platform uses token-based authentication. When you log in via the browser, you get a token that can be used in any HTTP client — including your Python notebook.

## Step by Step

1. **Log in** via browser at https://rmhtitiler.../
2. **Open Developer Tools** (F12 or right-click → Inspect)
3. **Go to Application tab** → Cookies or Local Storage
4. **Find the token** (usually named `access_token` or `id_token`)
5. **Copy the token value**

## Use in Python

```python
import os

# Option 1: Set as environment variable (recommended)
# export GEOSPATIAL_API_TOKEN="your-token-here"
token = os.environ.get("GEOSPATIAL_API_TOKEN")

# Option 2: Paste directly (less secure)
token = "your-token-here"

# Use in requests
import requests
response = requests.get(
    "https://rmhtitiler.../cog/info",
    params={"url": "..."},
    headers={"Authorization": f"Bearer {token}"}
)
```

## Token Expiration

Tokens typically expire after 1-8 hours. When you get a 401 error:
1. Return to browser
2. Refresh the page (may auto-renew)
3. Copy new token

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| 401 Unauthorized | Token expired | Get new token from browser |
| 403 Forbidden | Token valid but no access | Check permissions with admin |
| Invalid token | Copy/paste error | Re-copy, check for whitespace |
```

---

### Case Study: FATHOM Flood Data (fathom-flood-data.md)

```markdown
# Case Study: FATHOM Global Flood Data

## The Problem

FATHOM provides high-resolution flood risk data globally. Traditional approaches:

1. **Pre-rendered tiles**: Host 100s of TB of map tiles
   - Pro: Fast display
   - Con: Can't query actual values (click returns nothing)
   - Con: Storage costs astronomical

2. **Google Earth Engine**: Upload 8TB of data
   - Pro: Analysis possible
   - Con: Upload takes weeks
   - Con: GEE quotas and costs
   - Con: Vendor lock-in

## The Solution

Cloud-Optimized GeoTIFFs (COGs) on Azure + TiTiler:

```
┌─────────────────────────────────────────────────────────────┐
│                    Single COG File                          │
│                                                             │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐                     │
│  │ Display │  │ Point   │  │ Window  │                     │
│  │ Tiles   │  │ Query   │  │ Read    │                     │
│  │ /tiles  │  │ /point  │  │ rasterio│                     │
│  └─────────┘  └─────────┘  └─────────┘                     │
│       ↑            ↑            ↑                          │
│       └────────────┴────────────┘                          │
│              HTTP Range Requests                            │
│           (read only what you need)                         │
└─────────────────────────────────────────────────────────────┘
```

## Demo: Click to Get Flood Depth

```javascript
// MapLibre click handler
map.on('click', async (e) => {
  const { lng, lat } = e.lngLat;

  const response = await fetch(
    `https://rmhtitiler.../cog/point/${lng},${lat}?url=${cogUrl}`
  );
  const data = await response.json();

  new maplibregl.Popup()
    .setLngLat([lng, lat])
    .setHTML(`<strong>Flood depth:</strong> ${data.values[0].toFixed(2)}m`)
    .addTo(map);
});
```

## Results

| Metric | Pre-rendered | GEE | COG + TiTiler |
|--------|-------------|-----|---------------|
| Storage | 100s TB | 8 TB (upload) | 8 TB |
| Query values | No | Yes | Yes |
| Display speed | Fast | Medium | Fast |
| Cost | $$$$ | $$$ | $ |
| Setup time | Weeks | Weeks | Hours |

## Try It

[Live Demo: Rwanda Flood Risk Map](https://rmhtitiler.../demo/fathom)
```

---

## Implementation Steps

### Step 1: Set Up MkDocs

```bash
# In rmhtitiler repo
pip install mkdocs-material

# Create mkdocs.yml
cat > mkdocs.yml << 'EOF'
site_name: Geospatial APIs Documentation
theme:
  name: material
  palette:
    primary: indigo
  features:
    - navigation.tabs
    - navigation.sections
    - content.code.copy

nav:
  - Home: index.md
  - Web Developers:
    - Overview: guide/webdev/index.md
    - Concept Mapping: guide/webdev/concept-mapping.md
    - Quick Start: guide/webdev/quick-start.md
    - Recipes:
      - Replace Feature Service: guide/webdev/recipes/replace-feature-service.md
      - Display Raster: guide/webdev/recipes/display-raster.md
      - Spatial Query: guide/webdev/recipes/spatial-query.md
  - Data Scientists:
    - Overview: guide/analysis/index.md
    - Quick Start: guide/analysis/quick-start.md
    - Point Queries: guide/analysis/point-queries.md
    - Windowed Reads: guide/analysis/windowed-reads.md
    - STAC Search: guide/analysis/stac-search.md
  - Authentication: guide/auth/browser-to-notebook.md
  - Case Studies:
    - FATHOM Flood Data: case-studies/fathom-flood-data.md
  - API Reference: reference/index.md

markdown_extensions:
  - pymdownx.highlight
  - pymdownx.superfences
  - pymdownx.tabbed
  - admonition
  - tables
EOF
```

### Step 2: Create Directory Structure

```bash
mkdir -p docs/guide/webdev/recipes
mkdir -p docs/guide/analysis
mkdir -p docs/guide/auth
mkdir -p docs/case-studies
mkdir -p docs/reference
```

### Step 3: Integrate with FastAPI

```python
# In your FastAPI app
from fastapi.staticfiles import StaticFiles

# Serve MkDocs built site
app.mount("/guide", StaticFiles(directory="site", html=True), name="guide")

# Keep existing FastAPI docs
# /docs -> Swagger UI (auto-generated)
# /redoc -> ReDoc (auto-generated)
```

### Step 4: Build and Deploy

```bash
# Build docs
mkdocs build

# Or serve locally for development
mkdocs serve
```

---

## Cross-Reference with ETL Docs

The ETL Function App (`rmhgeoapi`) has its own documentation at:
- `/api/interface/swagger` - Swagger UI for Platform/ETL APIs
- `/api/interface/redoc` - ReDoc for Platform/ETL APIs
- `/api/openapi.json` - Raw OpenAPI 3.0 spec

**Note**: The ETL API exposes Platform endpoints (`/api/platform/*`) for data ingestion, not direct Job endpoints. Jobs are internal implementation details.

**Link strategy**:
- TiTiler docs link to ETL docs for "How to ingest data" (Platform API)
- ETL docs link to TiTiler docs for "How to consume data" (COG/STAC)

---

## Questions for TiTiler Claude

1. **Auth implementation**: What's your current auth mechanism? (Entra ID, API keys, etc.)
2. **Existing endpoints**: What endpoints exist beyond standard TiTiler?
3. **Deployment**: How is the app currently deployed? (Container Apps, App Service, etc.)
4. **Custom features**: Any custom endpoints for point queries or batch operations?

---

## Acceptance Criteria

- [ ] MkDocs site builds successfully
- [ ] Landing page with audience selector
- [ ] Web Developer Guide with concept mapping and quick start
- [ ] Data Scientist Guide with point query examples
- [ ] Auth flow documentation with screenshots
- [ ] FATHOM case study with working code examples
- [ ] Links to FastAPI auto-generated docs (/docs, /redoc)
- [ ] Served alongside FastAPI app

---

**Contact**: ETL Claude via `rmhgeoapi` codebase
**Reference**: `documentation_plan.md` in rmhgeoapi root
