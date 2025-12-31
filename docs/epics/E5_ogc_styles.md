## Epic E5: OGC Styles 🚧

**Business Requirement**: Support styling metadata for all data formats
**Status**: 🚧 PARTIAL
**Note**: Building capability first; population method (SLD ingest vs manual) TBD

### Feature F5.1: OGC API Styles ✅

**Deliverable**: CartoSym-JSON storage with multi-format output

| Story | Description |
|-------|-------------|
| S5.1.1 | Create Pydantic models |
| S5.1.2 | Build style translator (CartoSym → Leaflet/Mapbox) |
| S5.1.3 | Create repository layer |
| S5.1.4 | Implement service orchestration |
| S5.1.5 | Create GET /features/collections/{id}/styles |
| S5.1.6 | Create GET /features/collections/{id}/styles/{sid} |
| S5.1.7 | Add geo.feature_collection_styles table |

**Key Files**: `ogc_styles/`

**Tested**: 18 DEC 2025 - All three output formats verified (Leaflet, Mapbox GL, CartoSym-JSON)

---

### Feature F5.2: ETL Style Integration 📋 PLANNED

**Deliverable**: Auto-create default styles on vector ingest

| Story | Status | Description |
|-------|--------|-------------|
| S5.2.1 | 📋 | Design default style templates |
| S5.2.2 | 📋 | Integrate into process_vector job |

---

---
