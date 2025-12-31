## Epic E1: Vector Data as API ✅

**Business Requirement**: "Make vector data available as API"
**Status**: ✅ COMPLETE
**Completed**: NOV 2025

**Feature Overview**:
| Feature | Status | Scope |
|---------|--------|-------|
| F1.1 | ✅ | Vector ETL Pipeline |
| F1.2 | ✅ | OGC Features API |
| F1.3 | ✅ | Vector STAC Integration |
| F1.4 | ✅ | Vector Unpublish |
| F1.5 | ✅ | Vector Map Viewer |
| F1.6 | 🚧 | Enhanced Data Validation |

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

---

---
