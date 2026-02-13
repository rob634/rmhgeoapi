# D360 Geospatial Requirements Assessment

**Created**: 11 FEB 2026
**Source**: `D360.md` (requirements document)
**Scope**: rmhgeoapi (ETL) + rmhtitiler (Service API)

---

## System Architecture

| Layer | App | Role |
|-------|-----|------|
| **ETL** | `rmhgeoapi` | Ingest, transform, catalog (127+ endpoints, 36 job types) |
| **Service API** | `rmhtitiler` | Serve tiles, features, queries, statistics |

---

## Architectural Decisions (11 FEB 2026)

1. **Admin boundary hierarchy**: Admin2 table has admin1/admin0 columns. GROUP BY, not graph traversal.
2. **Anti-corruption rampart**: Client's tabular data structures are PARAMETERS at the Platform API boundary. They never reach internal schema.
3. **Access control**: Network-level separation (VNet for OUO, Cloudflare CDN+WAF for public). No app-level auth on data endpoints.
4. **Layer/boundary switching**: Front-end concern — different collection endpoint URLs.
5. **Data quality**: NOT our concern. Joins work or fail. No fuzzy matching. Validity for storage only.

---

## Requirements Assessment

### 1. Vector Data Display

| Req | Description | Status | Notes |
|-----|-------------|--------|-------|
| 1.1 | Display vector data | **MET** | ETL: `process_vector` / `vector_docker_etl`. Service: OGC Features + MVT |
| 1.2 | Dynamic scaling on zoom | **MET** | MVT auto-simplifies. PostGIS spatial index |
| 1.3 | Pre-defined zoom points | **PARTIAL** | Collection bbox exists. Missing: country/region lookup table |
| 1.4 | Data format ingestion | **MET** | Shapefile, GeoJSON, GeoPackage, GeoParquet |
| 1.5 | Geometry type support | **MET** | Point/line/polygon natively in PostGIS |
| 1.6 | Symbology / styling | **PARTIAL** | OGC Styles API exists (wrong app). Needs migration to Service API |
| 1.7 | Time-series visualization | **PARTIAL** | PostGIS stores temporal attrs. Missing: temporal query on vector tiles |
| 1.8 | Equal-Earth projection | **PARTIAL** | Multiple TMS supported. Missing: explicit Equal-Earth TMS |
| 1.9 | Legend information | **NOT MET** | No legend endpoint. **See: [D360_STYLES_LEGENDS_MIGRATION.md](./D360_STYLES_LEGENDS_MIGRATION.md)** |
| 1.10 | Map grid support | **PARTIAL** | Bbox filtering works. Missing: explicit region-grid endpoint |

### 2. Click / Highlight Interaction

| Req | Description | Status | Notes |
|-----|-------------|--------|-------|
| 2.1 | Feature selection & stats | **MET** | OGC Features items endpoint + `/cog/point/{lon},{lat}` |
| 2.2 | Raster stats on selection | **MET** | `POST /cog/statistics` accepts GeoJSON polygons |
| 2.3 | Boundary highlight on filter | **MET** | Feature queries return geometry |
| 2.4 | Hierarchical navigation | **MET** | Admin2 has admin1/admin0 columns → GROUP BY |
| 2.5 | Popup attributes | **MET** | Feature queries return all attributes |
| 2.6 | Extent retrieval | **PARTIAL** | Collection bbox exists. Per-feature computable from geometry |

### 3. Raster Data Display

| Req | Description | Status | Notes |
|-----|-------------|--------|-------|
| 3.1 | Raster tile serving | **MET** | `/cog/tiles/`, `/xarray/tiles/`, `/searches/{id}/tiles/` |
| 3.2 | Raster dynamic zoom | **MET** | COG overviews + TiTiler auto level-of-detail |
| 3.3 | Raster symbology | **MET** | TiTiler `colormap`, `rescale`, `color_formula` query params |
| 3.4 | Raster time-series | **PARTIAL** | Xarray/Zarr handles temporal. Missing: animation endpoint |
| 3.5 | Raster legend | **NOT MET** | **See: [D360_STYLES_LEGENDS_MIGRATION.md](./D360_STYLES_LEGENDS_MIGRATION.md)** |
| 3.6 | Raster map grid | **PARTIAL** | pgSTAC search filters by bbox |

### 4. Map Export

| Req | Description | Status | Notes |
|-----|-------------|--------|-------|
| 4.1 | Export support | **MET** | Standard XYZ/GeoJSON/MVT — client-side capture compatible |

### 5. Public vs Official-Use Data

| Req | Description | Status | Notes |
|-----|-------------|--------|-------|
| 5.1 | Access control | **MET** | Network-level: VNet (OUO) vs Cloudflare CDN (public) |
| 5.2 | Performance at scale | **MET** | Cloudflare CDN on external Service API |

### 6. Multiple Boundary Sets

| Req | Description | Status | Notes |
|-----|-------------|--------|-------|
| 6.1 | Boundary switching | **MET** | Front-end swaps collection endpoint URLs |
| 6.2 | Boundary versioning | **MET** | Semantic versioning in STAC collections |
| 6.3 | Boundary-data mapping | **REJECTED** | Data quality is client curation — not our concern |
| 6.4 | Named area matching | **REJECTED** | No fuzzy matching. Joins work or fail. |

### 7. Multi-Layer Data Exploration

| Req | Description | Status | Notes |
|-----|-------------|--------|-------|
| 7.1 | Multi-layer serving | **MET** | Multiple tile endpoints overlaid client-side |
| 7.2 | Layer catalog | **MET** | STAC API + OGC Features collections |
| 7.3 | Symbology customization | **PARTIAL** | TiTiler accepts per-request params. Missing: saved presets |
| 7.4 | Custom polygon zonal stats | **MET** | `POST /cog/statistics` accepts GeoJSON polygons |

### 8. Tabular Data to Boundary Linkage

| Req | Description | Status | Notes |
|-----|-------------|--------|-------|
| 8.1 | Geographic key mapping | **PARTIAL** | PostGIS joins on keys. Client submits join params |
| 8.2 | Choropleth rendering | **PARTIAL** | MVT tiles carry attributes. Client-side styling |
| 8.3 | Multi-dataset switching | **PARTIAL** | Different collection endpoints. Client swaps URLs |

### 9. Region Selection → Statistics

| Req | Description | Status | Notes |
|-----|-------------|--------|-------|
| 9.1 | Region click query | **MET** | Point queries + feature queries |
| 9.2 | Dynamic stats panel | **MET** | REST endpoints — per-selection calls |
| 9.3 | Raster zonal stats by region | **MET** | `POST /cog/statistics` + H3 raster aggregation |

---

## Summary Scorecard

| Category | Total | Met | Partial | Not Met | Rejected |
|----------|-------|-----|---------|---------|----------|
| 1. Vector Display | 10 | 4 | 5 | 1 | 0 |
| 2. Click/Highlight | 6 | 5 | 1 | 0 | 0 |
| 3. Raster Display | 6 | 3 | 2 | 1 | 0 |
| 4. Map Export | 1 | 1 | 0 | 0 | 0 |
| 5. Access Control | 2 | 2 | 0 | 0 | 0 |
| 6. Boundaries | 4 | 2 | 0 | 0 | 2 |
| 7. Multi-Layer | 4 | 3 | 1 | 0 | 0 |
| 8. Tabular Linkage | 3 | 0 | 3 | 0 | 0 |
| 9. Region Stats | 3 | 3 | 0 | 0 | 0 |
| **TOTAL** | **39** | **23 (59%)** | **12 (31%)** | **2 (5%)** | **2 (5%)** |

### Only 2 Genuine Gaps

Both are **legend metadata** (1.9 + 3.5) — addressed by the Styles & Legends Migration Plan.

### Remaining PARTIAL Items (Enhancement Opportunities)

| Req | Gap | Effort |
|-----|-----|--------|
| 1.3 | Country/region zoom-point lookup | Low — curated boundaries job exists |
| 1.6 | Styles API in wrong app | **Migration plan created** |
| 1.7 | Temporal query on vector tiles | Medium — TiPG CQL datetime filtering |
| 1.8 | Equal-Earth TMS | Low — custom TileMatrixSet config |
| 1.10 | Region-grid endpoint | Low — bbox subsetting |
| 2.6 | Per-feature extent | Trivial — computable from geometry |
| 3.4 | Raster time-series animation | Medium — temporal frame endpoint |
| 3.6 | Raster region-grid | Low — pgSTAC bbox filter |
| 7.3 | Saved symbology presets | Medium — render config storage |
| 8.1-8.3 | Tabular-to-boundary join | Client submits join params at rampart |
