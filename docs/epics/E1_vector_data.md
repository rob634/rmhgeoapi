## Epic E1: Vector Data as API 🚧

**Type**: Business
**Value Statement**: Any vector garbage you throw at us becomes clean, standardized, API-accessible data.
**Runs On**: E7 (Pipeline Infrastructure)
**Status**: 🚧 PARTIAL (Core ✅, Styles 🚧)
**Completed**: NOV 2025 (core features)

**Feature Overview**:
| Feature | Status | Scope |
|---------|--------|-------|
| F1.1 | ✅ | Vector ETL Pipeline |
| F1.2 | ✅ | OGC Features API |
| F1.3 | ✅ | Vector STAC Integration |
| F1.4 | ✅ | Vector Unpublish |
| F1.5 | ✅ | Vector Map Viewer |
| F1.6 | 🚧 | Enhanced Data Validation |
| F1.7 | ✅ | OGC API Styles |
| F1.8 | 📋 | ETL Style Integration |
| F1.9 | 📋 | ArcGIS Feature Service Integration |
| F1.10 | ✅ | Vector Tile Optimization (ST_Subdivide)

### Feature F1.1: Vector ETL Pipeline ✅

**Deliverable**: `process_vector` job with idempotent DELETE+INSERT pattern

| Story | Description |
|-------|-------------|
| S1.1.1 | Design etl_batch_id idempotency pattern |
| S1.1.2 | Create PostGIS handler with DELETE+INSERT |
| S1.1.3 | Implement chunked upload (500-row chunks) |
| S1.1.4 | Add spatial + batch index creation |
| S1.1.5 | Create process_vector job with JobBaseMixin |

**Key Files**: `jobs/process_vector.py`, `services/vector/process_vector_tasks.py`, `services/vector/postgis_handler.py`

---

### Feature F1.2: OGC Features API ✅

**Deliverable**: `/api/features/collections/{id}/items` with bbox queries

| Story | Description |
|-------|-------------|
| S1.2.1 | Create /api/features landing page |
| S1.2.2 | Implement /api/features/collections list |
| S1.2.3 | Add bbox query support |
| S1.2.4 | Create interactive map web interface |

**Key Files**: `web_interfaces/features/`, `triggers/ogc_features.py`

---

### Feature F1.3: Vector STAC Integration ✅

**Deliverable**: Items registered in pgSTAC `system-vectors` collection

| Story | Description |
|-------|-------------|
| S1.3.1 | Create system-vectors collection |
| S1.3.2 | Generate STAC items for vector datasets |
| S1.3.3 | Add vector-specific STAC properties |

**Key Files**: `infrastructure/pgstac_bootstrap.py`, `services/stac_metadata.py`

---

### Feature F1.4: Vector Unpublish ✅

**Deliverable**: `unpublish_vector` job for data removal

| Story | Description |
|-------|-------------|
| S1.4.1 | Create unpublish data models |
| S1.4.2 | Implement unpublish handlers |
| S1.4.3 | Add STAC item/collection validators |
| S1.4.4 | Create unpublish_vector job |

**Key Files**: `jobs/unpublish_vector.py`, `services/unpublish_handlers.py`, `core/models/unpublish.py`

**Note**: Code complete, needs deploy + test with `dry_run=true`

---

### Feature F1.5: Vector Map Viewer ✅ COMPLETE

**Deliverable**: Interactive Leaflet map viewer for browsing OGC Features collections
**Completed**: DEC 2025

| Story | Status | Description |
|-------|--------|-------------|
| S1.5.1 | ✅ | Create `VectorViewerService` with Leaflet HTML generation |
| S1.5.2 | ✅ | Add 30/70 sidebar+map layout |
| S1.5.3 | ✅ | Implement feature loading with limit/bbox/simplification controls |
| S1.5.4 | ✅ | Add click-to-inspect feature properties |
| S1.5.5 | ✅ | Add QA approve/reject section |

**Endpoint**: `/api/vector/viewer?collection={collection_id}`

**Key Files**: `vector_viewer/service.py`, `vector_viewer/triggers.py`

**Features**:
- OGC Features API integration (`/api/features/collections/{id}/items`)
- Pagination with limit control
- Bbox filtering (draw rectangle on map)
- Geometry simplification slider
- Feature property popup on click
- QA workflow buttons

---

### Feature F1.6: Enhanced Data Validation 🚧

**Deliverable**: Robust data validation during vector ETL to prevent garbage data from entering the database

| Story | Status | Description |
|-------|--------|-------------|
| S1.6.1 | ✅ | Datetime range validation - sanitize out-of-range timestamps (year > 9999) |
| S1.6.6 | ✅ | Antimeridian fix - split geometries crossing 180° longitude |
| SP1.6.2 | 📋 | **SPIKE**: Evaluate pandera for DataFrame validation |
| S1.6.3 | 📋 | Implement pandera-based validation schema (if spike approved) |
| S1.6.4 | 📋 | Add coordinate range validation (lat -90/90, lon -180/180) |
| S1.6.5 | 📋 | Add string length validation for TEXT columns |

**Spike SP1.6.2 Details**:
- **Goal**: Evaluate pandera library for dynamic DataFrame validation
- **Questions to Answer**:
  1. Can pandera handle dynamic schemas (unknown columns at runtime)?
  2. Performance impact on large GeoDataFrames?
  3. Integration complexity with existing `prepare_gdf()` workflow?
  4. Error reporting quality for user-facing messages?
- **Timebox**: 4 hours
- **Output**: Decision document + prototype if approved

**Key Files**: `services/vector/postgis_handler.py` (`prepare_gdf()`)

**Context (30 DEC 2025)**:
- KML files imported timestamps with year 48113 (garbage data)
- PostgreSQL accepted it (max year 294276) but psycopg crashed reading back (Python max year 9999)
- S1.6.1 implemented: out-of-range timestamps set to NULL with warning in job results
- Prompted discussion of systematic validation approach → pandera spike

**Antimeridian Fix (15 JAN 2026 - S1.6.6)**:
- Geometries crossing 180° longitude render incorrectly in web maps (edges span entire globe)
- Detects: coords > 180, coords < -180, or bbox width > 180°
- Solution: Split at antimeridian, shift parts to [-180, 180] range
- Returns MultiPolygon with valid parts on each side of the dateline
- Essential for country-level data (Russia, Fiji, New Zealand, etc.)

---

### Feature F1.7: OGC API Styles ✅

**Deliverable**: CartoSym-JSON storage with multi-format output
**Tested**: 18 DEC 2025 - All three output formats verified (Leaflet, Mapbox GL, CartoSym-JSON)

| Story | Description |
|-------|-------------|
| S1.7.1 | Create Pydantic models |
| S1.7.2 | Build style translator (CartoSym → Leaflet/Mapbox) |
| S1.7.3 | Create repository layer |
| S1.7.4 | Implement service orchestration |
| S1.7.5 | Create GET /features/collections/{id}/styles |
| S1.7.6 | Create GET /features/collections/{id}/styles/{sid} |
| S1.7.7 | Add geo.feature_collection_styles table |

**Key Files**: `ogc_styles/`

---

### Feature F1.8: ETL Style Integration 📋 PLANNED

**Deliverable**: Auto-create default styles on vector ingest

| Story | Status | Description |
|-------|--------|-------------|
| S1.8.1 | 📋 | Design default style templates |
| S1.8.2 | 📋 | Integrate into process_vector job |

---

### Feature F1.10: Vector Tile Optimization ✅ COMPLETE

**Deliverable**: `{table}_tiles` materialized views with ST_Subdivide for TiPG performance
**Completed**: 15 JAN 2026

| Story | Status | Description |
|-------|--------|-------------|
| S1.10.1 | ✅ | Implement ST_Subdivide materialized view creation in PostGIS handler |
| S1.10.2 | ✅ | Add automatic spatial GIST indexing on tile views |
| S1.10.3 | ✅ | Integrate tile view creation into process_vector Stage 3 |
| S1.10.4 | ✅ | Configure TiPG to serve tile views for complex polygon collections |

**Key Files**: `services/vector/postgis_handler.py` (`subdivide_complex_polygons` method)

**Technical Details**:
- Creates `{schema}.{table}_tiles` materialized view during vector ETL
- Complex polygons (>256 vertices) are subdivided using PostGIS `ST_Subdivide(geom, 256)`
- Simple polygons pass through unchanged (UNION ALL pattern)
- LATERAL join enables set-returning function for multi-row output
- Spatial GIST index created on `geom` column for fast tile queries

**Performance Metrics** (verified on test dataset):
- Original table: 1401 rows, max 2296 vertices, 406 complex polygons
- Tile view: 3982 rows, max 256 vertices, 0 complex polygons
- 89% reduction in maximum vertex count
- Execution time: ~638ms for view creation

**TiPG Integration**:
- TiPG vector tile server automatically discovers `_tiles` suffixed views
- Clipping operations during MVT generation are dramatically faster
- No changes required to TiPG configuration

---

### Feature F1.9: ArcGIS Feature Service Integration 📋 PLANNED

**Deliverable**: Import vector data from ArcGIS Feature Services (REST API) into rmhgeoapi
**Added**: 13 JAN 2026

| Story | Status | Description |
|-------|--------|-------------|
| SP1.9.1 | 📋 | **SPIKE**: ArcGIS Feature Service ETL Research |
| S1.9.2 | 📋 | Import public ArcGIS Feature Service |
| S1.9.3 | 📋 | Import authenticated ArcGIS Feature Service |
| S1.9.4 | 📋 | ESRI metadata → VectorMetadata translator |

**Spike SP1.9.1 Details**:
- **Goal**: Research ArcGIS Feature Service REST API and design ETL approach
- **Questions to Answer**:
  1. What is the ArcGIS REST API structure for Feature Services?
     - `/query` endpoint for feature retrieval (JSON format)
     - Pagination patterns (`resultOffset`, `resultRecordCount`)
     - Field metadata and geometry types
  2. How does ESRI authentication work?
     - Token-based auth via `/generateToken`
     - OAuth 2.0 for ArcGIS Online
     - Service account patterns for ArcGIS Enterprise
  3. How to translate ESRI metadata to VectorMetadata?
     - Field definitions → column types
     - Spatial reference → EPSG codes
     - Symbology → potential OGC Styles integration (F1.7)
  4. Rate limiting and pagination strategies?
     - `maxRecordCount` server limit (typically 1000-2000)
     - Offset-based pagination vs OID-based pagination
- **Timebox**: 4 hours
- **Output**: Decision document with:
  - Sample ArcGIS Feature Service URLs for testing
  - ESRI → VectorMetadata field mapping table
  - Authentication flow diagrams
  - Recommended implementation approach

**Story S1.9.2: Import Public Feature Service**:
- **Goal**: Demonstrate import from publicly accessible ArcGIS Feature Service
- **Input**: Feature Service URL (e.g., `https://services.arcgis.com/.../FeatureServer/0`)
- **Output**: Vector data in PostGIS + STAC item in `system-vectors`
- **Example Sources**:
  - ESRI Living Atlas public layers
  - State/local government open data portals
  - USGS, NOAA, EPA public services

**Story S1.9.3: Import Authenticated Feature Service**:
- **Goal**: Demonstrate import from protected ArcGIS Feature Service
- **Input**: Feature Service URL + credentials (token or OAuth)
- **Output**: Same as S1.9.2
- **Considerations**:
  - Credential storage (Key Vault integration)
  - Token refresh for long-running imports
  - Error handling for auth failures

**Story S1.9.4: ESRI Metadata Translator**:
- **Goal**: Convert ESRI field definitions and symbology to VectorMetadata
- **ESRI Metadata Elements**:
  - `fields[]` → column definitions (name, type, alias, domain)
  - `geometryType` → PostGIS geometry type
  - `spatialReference.wkid` → SRID
  - `drawingInfo.renderer` → potential OGC Style (F1.7)
- **Output**: `VectorMetadata` instance ready for STAC registration

**Key Integration Points**:
- Reuses existing `PostGISHandler` for data loading
- Reuses existing `VectorMetadata` model (F7.8)
- Reuses existing OGC Styles infrastructure (F1.7) for symbology
- New: ArcGIS REST client module

---

---
