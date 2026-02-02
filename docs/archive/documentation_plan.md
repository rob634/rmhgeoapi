# Documentation Architecture Plan: GeoDataHub Platform

## Overview

This document outlines the documentation strategy for the GeoDataHub platform, which consists of two distinct API surfaces with different audiences and security requirements.

## Architecture

### Two Separate Documentation Deployments

**1. Consumer-Facing Docker App (TiTiler/TiPG)**
- Serves: tile endpoints, feature services, STAC catalog, point queries
- Audience: web developers, data scientists
- Auth: browser-based, tokens transferable to notebooks
- Docs location: served from the FastAPI app itself

**2. B2B ETL Function App**
- Serves: job orchestration, pipeline management, internal APIs
- Audience: internal systems, trusted partners
- Auth: separate B2B security model
- Docs location: needs OpenAPI generation added (see below)

Keep these separate - different audiences, different auth stories, different security boundaries.

---

## Part 1: Function App ETL API Documentation

### Task: Add OpenAPI/Swagger/ReDoc to Azure Functions

The Function App doesn't have built-in OpenAPI generation like FastAPI. Implement one of these approaches:

#### Option A: Build-time spec generation (recommended)
1. Create a script that introspects existing Pydantic models
2. Generate `openapi.json` from model schemas
3. Manually define endpoint paths/methods in a template
4. Serve static HTML pages for Swagger UI and ReDoc

#### Option B: Lightweight FastAPI wrapper
1. Single HTTP trigger function dedicated to docs
2. Mounts a minimal FastAPI app
3. Routes documented but marked as "served elsewhere"
4. Serves `/docs`, `/redoc`, `/openapi.json`

### Implementation Details

**Swagger UI HTML (serve at `/docs` or `/api/docs`):**
```html
<!DOCTYPE html>
<html>
<head>
  <title>GeoDataHub ETL API</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    SwaggerUIBundle({
      url: "/api/openapi.json",
      dom_id: '#swagger-ui'
    });
  </script>
</body>
</html>
```

**ReDoc HTML (serve at `/redoc` or `/api/redoc`):**
```html
<!DOCTYPE html>
<html>
<head>
  <title>GeoDataHub ETL API Reference</title>
  <link href="https://fonts.googleapis.com/css?family=Montserrat:300,400,700" rel="stylesheet">
  <style>body { margin: 0; padding: 0; }</style>
</head>
<body>
  <redoc spec-url="/api/openapi.json"></redoc>
  <script src="https://cdn.redoc.ly/redoc/latest/bundles/redoc.standalone.js"></script>
</body>
</html>
```

**OpenAPI Spec Generation:**
- Extract JSON schemas from existing Pydantic models (JobSubmission, PipelineConfig, etc.)
- Assemble into OpenAPI 3.0+ structure
- Include: paths, request/response schemas, auth requirements, error responses

---

## Part 2: Consumer-Facing Documentation (Docker App)

### Dual-Track Documentation Strategy

The same API endpoints serve two distinct audiences with different mental models and workflows. Create audience-specific entry points that funnel into shared reference documentation.

### Track A: Web Developers (Internal Team)

**Primary goal:** Replace ArcGIS/GEE workflows with standards-based alternatives

**Landing page:** `/docs/guide/webdev` or similar

**Content structure:**

```markdown
# Web Developer Guide: Building Maps with GeoDataHub

## Why Migrate from ArcGIS/GEE
- Cost comparison (30-100x savings)
- Performance benchmarks
- Standards-based = portable skills, no vendor lock-in

## Concept Mapping

| You're used to...              | Here it's...                     |
|--------------------------------|----------------------------------|
| ArcGIS Feature Service         | TiPG `/collections/{id}/items`   |
| ArcGIS Map Service tiles       | TiTiler `/cog/tiles/{z}/{x}/{y}` |
| Portal item search             | STAC catalog `/search`           |
| ArcGIS JS SDK (800kb)          | MapLibre GL JS (30kb)            |
| GEE ImageCollection            | STAC collection + COG access     |
| esriGeometryPolygon            | GeoJSON (actual standard)        |

## Quick Start: Tiles in 5 Minutes

[MapLibre code snippet showing MVT consumption]

## Recipes

### "I have a Feature Service I need to replace"
[Step-by-step with code]

### "I need to display raster imagery"
[COG + TiTiler example]

### "I need to query features spatially"
[TiPG CQL filtering example]

### "I need point values from a raster" (the FATHOM example)
[Point query endpoint + response]
```

### Track B: Data Scientists (External Clients)

**Primary goal:** Access and analyze data without downloading entire datasets

**Landing page:** `/docs/guide/analysis` or similar

**Content structure:**

```markdown
# Data Scientist Guide: Cloud-Native Geospatial Analysis

## Philosophy: Compute Goes to Data
- No more downloading 50GB files
- HTTP range requests = read only what you need
- Same file serves tiles, point queries, and windowed analysis

## Quick Start: Query Data in 5 Minutes

### From a Notebook (Python)
[requests/rasterio/geopandas examples]

### Authentication: Browser to Notebook
[Link to dedicated auth page]

## Access Patterns

### Point Queries
"I need the flood depth at this coordinate"
[Code example with response]

### Windowed Reads (COG)
"I need a 1km buffer around my study area"
[Rasterio windowed read example]

### Vector Queries
"I need all features intersecting my polygon"
[TiPG CQL query example]

### STAC Search
"What datasets are available for Rwanda?"
[pystac-client example]

## Format Reference
- COG: when to use, how to access
- MVT: what it is, when you'd care
- GeoJSON: feature queries
- STAC: catalog search and discovery
```

### Dedicated Page: Browser Auth to Notebook

**Location:** `/docs/guide/auth-notebook`

This workflow is non-obvious and deserves its own page with screenshots.

```markdown
# Using Your Browser Token in a Notebook

## Why This Works
[Brief explanation of token-based auth]

## Step by Step
1. Log in via browser at [app URL]
2. Open developer tools (F12)
3. Find the token in [specific location]
4. Copy to your notebook
5. Use in requests header

## Code Template
[Python snippet with auth header]

## Token Expiration
[What to do when it expires]

## Troubleshooting
[Common issues]
```

### Shared Reference Documentation

Both tracks link to the auto-generated OpenAPI docs for complete endpoint reference:
- `/docs` - Swagger UI (interactive testing)
- `/redoc` - ReDoc (clean reading/reference)

---

## Tooling Recommendations

### For Narrative Documentation
- **MkDocs** with Material theme, or
- **Docusaurus**
- Serves alongside the auto-generated API reference

### Structure
```
/docs/guide/webdev     → Web developer migration guide
/docs/guide/analysis   → Data scientist workflows  
/docs/guide/auth       → Browser-to-notebook auth
/docs                  → Swagger UI (auto-generated)
/redoc                 → ReDoc (auto-generated)
/openapi.json          → Raw OpenAPI spec
```

---

## Case Study to Include: FATHOM Flood Data

This is the "killer demo" - document it as a case study in both tracks.

**The problem:**
- Previously: host 100s of TB of pre-rendered tiles (can't query values) OR upload 8TB to GEE and hope
- Neither option: click on map, get actual flood depth value

**The solution:**
- COGs on Azure blob storage
- TiTiler serves tiles on demand (fast rendering at any zoom)
- Point query endpoint returns actual values (click → data)
- Same source file, multiple access patterns, no preprocessing

**Include:**
- Screenshot of Rwanda example
- Code snippet for point query
- Performance notes

---

## Summary of Work

1. **Function App:** Add OpenAPI generation + Swagger/ReDoc HTML endpoints
2. **Docker App:** Add narrative documentation (MkDocs/Docusaurus) alongside existing FastAPI auto-docs
3. **Write content:**
   - Web dev migration guide (the "ArcGIS killing document")
   - Data scientist analysis guide
   - Auth flow explainer
   - FATHOM case study