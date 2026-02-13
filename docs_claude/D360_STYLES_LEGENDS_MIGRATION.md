# D360 Styles & Legends Migration Plan

**Created**: 11 FEB 2026
**Status**: Approved - Ready for Implementation
**Epic**: Geospatial API for DDH
**Feature**: F5 - Service Layer (TiTiler/TiPG)
**Scope**: Cross-repo (rmhgeoapi ETL + rmhtitiler Service API)

---

## Problem Statement

OGC Styles serving was built in the ETL app (rmhgeoapi) but belongs in the Service API (rmhtitiler / "geotiler"). All B2C serving concerns — styles, legends, render configs — must live in the Service API layer. The database is the shared contract between ETL (writes) and Service API (reads).

```
ETL (rmhgeoapi) WRITES                  Service API (rmhtitiler) READS & SERVES
──────────────────────                   ──────────────────────────────────────
COGs → Blob Storage                  →   TiTiler serves tiles
Features → PostGIS                   →   TiPG serves OGC Features + MVT
STAC items → pgstac                  →   stac-fastapi serves STAC API
Styles → geo.feature_collection_styles → OGC Styles API + Legends (THIS PLAN)
Render configs → app.raster_render_configs → Render config API + Legends (THIS PLAN)
```

### D360 Requirements Addressed

| Req | Description | Gap |
|-----|-------------|-----|
| **1.9** | Legend information (vector) | No legend endpoint exists |
| **3.5** | Raster legend | No legend endpoint exists |
| **1.6** | Symbology / styling | Styles API exists in wrong app |
| **3.3** | Raster symbology | Render config endpoints disabled |
| **7.3** | Layer symbology customization | Render configs not served |

---

## Architecture Decision

### Anti-Corruption Layer Principle

The client's tabular data structures NEVER reach our internal schema. Styles, legends, colormaps, and render parameters are all stored as JSONB blobs. The client submits visualization preferences as job parameters during ingestion:

```python
# Client submits (parameters at the rampart)
{
    "style": {"fill_color": "#228B22", "stroke_color": "#2266cc"},
    "colormap_name": "blues",
    "rescale": [[0, 5]]
}

# ETL writes to PostgreSQL (structured JSONB)
# Service API reads and serves via REST
```

### No OGC Legend Standard

Research confirmed (11 FEB 2026):
- **OGC API - Styles** (draft spec 20-009): Zero mention of legends
- **STAC Render Extension** (v2.0.0): Covers render params but no legend object
- **Conclusion**: Legends are just JSON objects derived from style/render metadata

---

## Phase 1: Vector Styles + Legends (rmhtitiler)

### New Files to Create

| File (in rmhtitiler) | Purpose | Source |
|----------------------|---------|--------|
| `geotiler/services/styles_models.py` | Pydantic models (CartoSym-JSON, API responses) | Copy from `rmhgeoapi/ogc_styles/models.py` — pure Python, 0 Azure deps, 163 lines |
| `geotiler/services/styles_translator.py` | CartoSym → Leaflet/Mapbox conversion | Copy from `rmhgeoapi/ogc_styles/translator.py` — pure Python, 0 deps, 384 lines |
| `geotiler/services/styles_db.py` | asyncpg queries (read-only) | Rewrite of `rmhgeoapi/ogc_styles/repository.py` read methods (psycopg → asyncpg) |
| `geotiler/services/legend_generator.py` | Derive legend JSON from style_spec/render_spec | Brand new — ~150 lines |
| `geotiler/routers/styles.py` | FastAPI router | Replaces `rmhgeoapi/ogc_styles/triggers.py`, follows diagnostics.py pattern |

### Files to Modify

| File | Change |
|------|--------|
| `geotiler/app.py` | Add `app.include_router(styles.router, tags=["Styles & Legends"])` |

### New Endpoints (6 total)

```
# Vector Styles (from geo.feature_collection_styles)
GET /styles/collections/{collection_id}/styles                    # List styles for collection
GET /styles/collections/{collection_id}/styles/{style_id}         # Get style (?f=leaflet|mapbox|cartosym)
GET /styles/collections/{collection_id}/styles/{style_id}/legend  # Vector legend JSON

# Raster Render Configs (from app.raster_render_configs)
GET /styles/renders/{cog_id}                                      # List render configs for COG
GET /styles/renders/{cog_id}/{render_id}                          # Get render config
GET /styles/renders/{cog_id}/{render_id}/legend                   # Raster legend JSON
```

### Database Access Pattern

Use existing TiPG asyncpg pool (`app.state.pool`). Follow diagnostics.py pattern:

```python
async def get_style(pool, collection_id: str, style_id: str):
    query = """
        SELECT style_id, title, description, style_spec, is_default
        FROM geo.feature_collection_styles
        WHERE collection_id = $1 AND style_id = $2
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, collection_id, style_id)
        return dict(row) if row else None
```

**Key decisions:**
- Fully-qualified schema names (`geo.`, `app.`) — no search_path changes
- asyncpg auto-deserializes JSONB to Python dicts
- No ORM, raw SQL only (matches rmhtitiler patterns)
- 503 response if pool not initialized (graceful degradation)

### Legend JSON Format

```json
{
  "type": "vector",
  "title": "Land Cover",
  "geometry_type": "Polygon",
  "entries": [
    {
      "label": "Forest",
      "symbol": {"type": "polygon", "fill_color": "#228B22", "fill_opacity": 1.0, "stroke_color": "#2266cc", "stroke_width": 1},
      "filter_property": "class",
      "filter_value": "forest"
    },
    {
      "label": "Urban",
      "symbol": {"type": "polygon", "fill_color": "#808080", "fill_opacity": 1.0, "stroke_color": "#2266cc", "stroke_width": 1},
      "filter_property": "class",
      "filter_value": "urban"
    }
  ]
}
```

```json
{
  "type": "raster",
  "title": "Flood Depth (m)",
  "colormap_name": "blues",
  "continuous": true,
  "min_value": 0,
  "max_value": 5
}
```

Legends are **derived on-the-fly** from `style_spec` / `render_spec` JSONB — no new database table needed.

---

## Phase 2: Database Permissions

```sql
-- Geotiler DB user needs SELECT on app schema for raster render configs
GRANT USAGE ON SCHEMA app TO <geotiler_user>;
GRANT SELECT ON app.raster_render_configs TO <geotiler_user>;

-- Verify geo schema access (should already work via TiPG)
GRANT SELECT ON geo.feature_collection_styles TO <geotiler_user>;
```

---

## Phase 3: Deprecate rmhgeoapi Style Endpoints

1. Add `Deprecation: true` header to `ogc_styles/triggers.py` responses
2. Eventually remove read-only routes from `function_app.py` (lines 924-933)
3. **Keep permanently in ETL**:
   - `ogc_styles/repository.py` write methods (`create_default_style_for_collection`)
   - `ogc_styles/models.py` (used by repository)
   - `services/handler_vector_docker_complete.py:198` → `_create_default_style()` call
   - `infrastructure/raster_render_repository.py` write methods

---

## What Stays in rmhgeoapi (ETL) Permanently

| File | Why |
|------|-----|
| `ogc_styles/repository.py` (write methods only) | ETL creates default styles during vector ingestion |
| `ogc_styles/models.py` | Used by repository for CartoSym-JSON construction |
| `services/handler_vector_docker_complete.py:198` | Write call site during vector ETL |
| `infrastructure/raster_render_repository.py` (write methods) | ETL creates render configs during raster ingestion |
| `core/models/raster_render_config.py` | Model definition for render configs |

---

## Verification Plan

1. Deploy rmhtitiler with new styles router
2. Test vector styles:
   ```bash
   curl https://<titiler>/styles/collections/<existing_table>/styles
   curl https://<titiler>/styles/collections/<table>/styles/default?f=leaflet
   curl https://<titiler>/styles/collections/<table>/styles/default/legend
   ```
3. Test raster renders (after Phase 2 DB grants):
   ```bash
   curl https://<titiler>/styles/renders/<cog_id>
   curl https://<titiler>/styles/renders/<cog_id>/default/legend
   ```
4. Run vector ETL job → verify style appears in rmhtitiler endpoints
5. Compare rmhtitiler style output with rmhgeoapi output (should be identical)

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| asyncpg JSONB returns string not dict | Add `set_type_codec('jsonb', ...)` on pool setup if needed |
| `app` schema not accessible to geotiler user | Phase 2 GRANT statements (blocker for raster renders only) |
| Base URL detection behind reverse proxy | Use `X-Forwarded-Host` header or `STYLES_BASE_URL` config |
| Breaking rmhgeoapi consumers during transition | Keep both endpoints active; deprecate rmhgeoapi later |

---

## Reference: Existing Code Locations

### rmhgeoapi (ETL) — Source Code

| File | Lines | Purpose |
|------|-------|---------|
| `ogc_styles/models.py` | 163 | CartoSym-JSON Pydantic models |
| `ogc_styles/translator.py` | 384 | CartoSym → Leaflet/Mapbox |
| `ogc_styles/repository.py` | 416 | PostgreSQL CRUD (psycopg) |
| `ogc_styles/service.py` | 305 | Business logic orchestrator |
| `ogc_styles/triggers.py` | 292 | Azure Functions HTTP handlers |
| `core/models/raster_render_config.py` | 383 | Raster render model + to_titiler_params() |
| `services/raster_render_service.py` | 417 | Raster render business logic |
| `infrastructure/raster_render_repository.py` | 474 | Raster render DB access |
| `function_app.py:924-933` | — | Style endpoint registration |
| `function_app.py:942-964` | — | Raster render endpoints (DISABLED) |

### rmhtitiler (Service API) — Pattern References

| File | Purpose |
|------|---------|
| `geotiler/routers/diagnostics.py` | asyncpg `_run_query()` pattern to follow |
| `geotiler/routers/vector.py` | TiPG pool initialization reference |
| `geotiler/app.py` | Router registration pattern |
| `geotiler/services/database.py` | Pool access utilities |
| `geotiler/auth/postgres.py` | Database auth (Managed Identity) |

### Database Tables

| Table | Schema | Used By |
|-------|--------|---------|
| `geo.feature_collection_styles` | geo | Vector styles (CartoSym-JSON in `style_spec` JSONB) |
| `app.raster_render_configs` | app | Raster renders (TiTiler params in `render_spec` JSONB) |
