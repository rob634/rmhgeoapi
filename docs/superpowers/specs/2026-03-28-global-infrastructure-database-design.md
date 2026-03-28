# Global Infrastructure Database (GID) Pipeline Design Spec

**Date**: 28 MAR 2026
**Status**: Draft
**Author**: Robert + Claude Prime
**Source Repo**: https://github.com/SebKrantz/Global-Infrastructure-Database
**Source Author**: Sebastian Krantz

---

## Purpose

Replicate the Global Infrastructure Database pipeline as a set of DAG workflows in our orchestration system. The original pipeline (R `targets` + 2 Python scripts) aggregates infrastructure data from 18+ sources across all low- and middle-income countries (LMICs), harmonizes ~60 infrastructure categories, and produces a unified hexagonal grid dataset.

Our implementation: pure Python handlers (with R subprocess for `osmclass` classification), DuckDB + GeoParquet as the data backbone, Bronze/Silver/PostGIS output tiers, H3 Res 6 hex aggregation, and one workflow per major data source.

---

## Scope

### In Scope

- All 18+ data sources from the original pipeline
- Full category harmonization (OSM-based taxonomy, ~60 categories)
- H3 Res 6 hex aggregation (replacing DGGRID R12)
- Bronze → Silver → PostGIS tier flow
- STAC registration of output datasets
- R `osmclass` integration via r2u + subprocess (with documented Python port path)
- Overture/Foursquare category mappings extracted to JSON/YAML config

### Out of Scope

- Data sources mentioned in `DATA.md` but not yet implemented (SFI GeoAsset, GRIP roads, OOKLA, AfterFibre, etc.) — these become future workflow additions using the same patterns
- Frontend visualization (existing OGC Features API / TiPG serves the data)
- Scheduling (existing DAGScheduler handles periodic re-runs once workflows exist)

### Spikes (Investigation Required Before Implementation)

- **SPIKE-01: OSM-vs-Overture gap analysis** — Determine which OSM infrastructure categories are NOT covered by Overture Places/Transportation. Select lightweight access pattern for the remainder (ohsome API, Overture base layer, or Geofabrik Parquet). Acceptance criteria: documented category gap matrix + recommended access method + memory profile under 8GB.
- **SPIKE-02: osmclass mapping extraction** — Extract the complete classification dictionary from the `osmclass` R package as a JSON file. Verify completeness against the R package source. This JSON serves as the authoritative taxonomy reference regardless of whether classification runs in R or Python.
- **SPIKE-03: Overture/Foursquare mapping extraction** — Extract the 46KB `overture_foursquares_to_osm_det.R` mapping table into a structured JSON/YAML config. Verify category coverage against original.

---

## Architecture Overview

### Design Principles

1. **One workflow per source family** — Each major data source gets its own YAML workflow. Sources can be ingested independently.
2. **DuckDB + GeoParquet everywhere** — S3 Parquet queries via DuckDB, intermediate storage as GeoParquet, no PBF/QS/proprietary formats.
3. **Bronze landing zone is universal** — All raw inputs land in Bronze blob storage before processing.
4. **R via subprocess, not embedding** — `osmclass` runs as an Rscript subprocess. Data exchange via GeoParquet files on the mount. No rpy2 coupling.
5. **Copy to mount first** — Per existing project convention, all ETL copies Bronze → mount before processing. No direct cloud reads.
6. **Respect the author's taxonomy** — Classification mappings are extracted as explicit, auditable config files (JSON/YAML) so R-domain experts can verify equivalence.

### System Context

```
┌─────────────────────────────────────────────────────────────┐
│                    DAG Brain (Orchestrator)                  │
│                                                             │
│  gid_overture_places.yaml    gid_gem_power.yaml            │
│  gid_foursquare.yaml         gid_osm_classified.yaml       │
│  gid_alltheplaces.yaml       gid_combine_points.yaml       │
│  gid_opencellid.yaml         gid_aggregate_hex.yaml         │
│  gid_portswatch.yaml         gid_overture_transport.yaml   │
│  gid_ogim.yaml               gid_egm_grid.yaml            │
│  gid_gem_cement.yaml         gid_aggregate_lines.yaml      │
│  gid_gem_iron.yaml           gid_combine_hex.yaml          │
│  gid_gem_chemicals.yaml      gid_solar_assets.yaml         │
│  gid_gem_steel.yaml          gid_itu_nodes.yaml            │
│  gid_ozm_zones.yaml          gid_master.yaml (coordinator) │
│                                                             │
└──────────────────────┬──────────────────────────────────────┘
                       │ claims READY tasks
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                  Docker Worker(s)                            │
│                                                             │
│  Python handlers:          R subprocess:                    │
│  • gid_fetch_*             • osmclass classification        │
│  • gid_process_*                                            │
│  • gid_classify_*          DuckDB:                          │
│  • gid_combine_*           • S3 Parquet queries             │
│  • gid_aggregate_*         • Local Parquet queries          │
│  • gid_load_postgis_*      • H3 extension                  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
         │                           │
         ▼                           ▼
┌─────────────────┐    ┌──────────────────────────┐
│  Azure Blob     │    │  PostgreSQL (PostGIS)     │
│                 │    │                          │
│  Bronze:        │    │  silver.gid_points       │
│  • raw downloads│    │  silver.gid_hex_points   │
│  • static Excel │    │  silver.gid_hex_lines    │
│  • config files │    │  silver.gid_hex_combined │
│                 │    │                          │
│  Silver:        │    │  pgstac:                 │
│  • GeoParquet   │    │  • GID collections       │
│  • processed    │    │                          │
└─────────────────┘    └──────────────────────────┘
```

---

## Data Sources Inventory

### A. Remote-Fetched Sources (handlers download at runtime)

| # | Source | ID Prefix | Access Method | Format | Handler Pattern |
|---|--------|-----------|---------------|--------|----------------|
| 1 | OpenStreetMap | OSM | **SPIKE-01 outcome** (NOT Geofabrik PBF scraping) | TBD (likely Parquet or API) | gid_fetch_osm → gid_classify_osm |
| 2 | Overture Maps Places | OVP | DuckDB → S3 Parquet (`s3://overturemaps-us-west-2/release/{version}/theme=places/`) | Parquet | gid_fetch_overture_places |
| 3 | Foursquare OS Places | FSP | DuckDB → S3 Parquet (paths from documented API, NOT HTML scraping) | Parquet | gid_fetch_foursquare |
| 4 | AllThePlaces | ATP | REST API to `data.alltheplaces.xyz` (structured endpoint, not HTML scrape) | ZIP → GeoJSON → GeoParquet | gid_fetch_alltheplaces → gid_process_alltheplaces |
| 5 | OpenCellID | OCID | Direct URL download (token-authenticated CSV.GZ) | CSV.GZ → GeoParquet | gid_fetch_opencellid |
| 6 | PortWatch (IMF) | PW | ArcGIS REST FeatureServer query (paginated JSON) | GeoJSON → GeoParquet | gid_fetch_portswatch |
| 7 | OGIM (Oil & Gas) | OGIM | Zenodo API → latest version → GPKG download | GeoPackage → GeoParquet | gid_fetch_ogim |
| 8 | EGM Grid (Gridfinder) | EGM | Zenodo API → latest version → GPKG download | GeoPackage → GeoParquet | gid_fetch_egm_grid |
| 9 | Overture Transportation | OVT | DuckDB → S3 Parquet (`theme=transportation/type=segment/`) | Parquet | gid_fetch_overture_transport |

### B. Static Sources (pre-loaded to Bronze, handlers read from there)

| # | Source | ID Prefix | Original Format | Bronze Path |
|---|--------|-----------|-----------------|-------------|
| 10 | GEM Global Integrated Power | GIP | Excel (.xlsx, sheet 2) | `bronze/gid/gem/global-integrated-power.xlsx` |
| 11 | GEM Cement & Concrete | GEMCEM | Excel (.xlsx, sheet "Plant Data") | `bronze/gid/gem/cement-concrete.xlsx` |
| 12 | GEM Iron Ore Mines | GEMIRON | Excel (.xlsx, sheet "Main Data") | `bronze/gid/gem/iron-ore-mines.xlsx` |
| 13 | GEM Chemicals Inventory | GEMCHEM | Excel (.xlsx, sheet "Plant data") | `bronze/gid/gem/chemicals-inventory.xlsx` |
| 14 | GEM Iron & Steel | GEMSTEEL | Excel (.xlsx, sheets "Plant data" + "Plant capacities") | `bronze/gid/gem/iron-steel.xlsx` |
| 15 | TZ-SAM Solar Assets | SAM | CSV | `bronze/gid/sam/solar-assets.csv` |
| 16 | ITU Telecom Nodes | ITU | GeoJSON | `bronze/gid/itu/node-ties.geojson` |
| 17 | Open Zone Map | OZM | CSV | `bronze/gid/ozm/open-zone-map.csv` |
| 18 | EarthEnv Landcover | LAND | GeoTIFF | `bronze/gid/landcover/open-water.tif` |

### C. Reference/Config Data (checked into repo or Bronze)

| Item | Format | Purpose |
|------|--------|---------|
| `osmclass` taxonomy | JSON (extracted from R package — SPIKE-02) | OSM tag → infrastructure category mapping |
| Overture category mapping | JSON/YAML (extracted from R code — SPIKE-03) | Overture category → OSM category mapping |
| Foursquare category mapping | JSON/YAML (extracted from R code — SPIKE-03) | Foursquare category → OSM category mapping |
| LMIC country list | JSON (derived from World Bank API at build time) | Country filter for all sources |
| Overture release version | Runtime parameter | Which Overture release to query |

---

## Unified Point Schema

All point sources are normalized to this 16-column schema before combination. This replicates the original exactly.

```
source            TEXT     -- dataset prefix (OSM_points, OVP, FSP, ATP, OCID, GIP, etc.)
id                TEXT     -- unique ID: {PREFIX}_{native_id}
lon               FLOAT8   -- WGS84 longitude
lat               FLOAT8   -- WGS84 latitude
ref               TEXT     -- native reference ID
name              TEXT     -- feature name
address           TEXT     -- formatted address
source_orig       TEXT     -- original data source attribution
main_cat          TEXT     -- primary infrastructure category (~60 values)
main_tag          TEXT     -- classification tag name
main_tag_value    TEXT     -- classification tag value
alt_cats          TEXT     -- pipe-separated alternative categories
alt_tags_values   TEXT     -- pipe-separated alternative tag values
other_tags_values TEXT     -- additional metadata as key=value string
variable          TEXT     -- measurement variable name (e.g., "capacity_mw")
value             FLOAT8   -- measurement value
```

### Infrastructure Categories (~60)

The full harmonized taxonomy (representative sample):

`accommodation`, `automotive`, `commercial`, `communications_network`, `construction`, `education_essential`, `education_other`, `emergency`, `farming`, `financial`, `food`, `health_essential`, `health_other`, `industrial`, `institutional`, `military`, `mining`, `office_other`, `parks_and_nature`, `port`, `power_other`, `power_plant_large`, `power_plant_small`, `public_service`, `public_transport`, `religion`, `residential`, `SEZ`, `shopping_essential`, `shopping_other`, `sports`, `storage`, `transport_infrastructure`, `utilities_other`, `waste`, `water_transport`, `wholesale`, ...

Full list to be extracted during SPIKE-02/SPIKE-03.

---

## Workflow Decomposition

### Tier 1: Source Fetch + Process Workflows (Independent, Parallelizable)

Each source family gets its own workflow. All follow the same pattern:

```
fetch (download to Bronze) → process (normalize to unified schema) → write Silver GeoParquet
```

#### W-01: `gid_overture_places.yaml`

```yaml
workflow: gid_overture_places
parameters:
  overture_release: {type: str, required: true}
  country_filter: {type: str, required: true, description: "Path to LMIC country list JSON"}

nodes:
  fetch_lmic_list:
    type: task
    handler: gid_load_country_filter
    params: [country_filter]
    # Loads the LMIC country list from Bronze/config

  fetch_overture_places:
    type: task
    handler: gid_fetch_overture_places
    depends_on: [fetch_lmic_list]
    receives:
      countries: "fetch_lmic_list.result.countries"
    params: [overture_release]
    # DuckDB query against S3 Parquet, filtered to LMIC countries
    # Output: GeoParquet in Bronze

  fetch_overture_categories:
    type: task
    handler: gid_fetch_overture_categories
    params: [overture_release]
    # Downloads Overture category CSV from GitHub
    # Output: category taxonomy in Bronze

  classify_overture:
    type: task
    handler: gid_classify_overture
    depends_on: [fetch_overture_places, fetch_overture_categories]
    receives:
      places_path: "fetch_overture_places.result.output_path"
      categories_path: "fetch_overture_categories.result.output_path"
    # Applies Overture→OSM category mapping (from JSON config)
    # Normalizes to unified 16-column schema
    # Output: Silver GeoParquet
```

**Handler details:**

- `gid_fetch_overture_places`: Uses DuckDB with `httpfs` + `spatial` extensions. Queries `s3://overturemaps-us-west-2/release/{version}/theme=places/*/*`. Filters by country bounding boxes from LMIC list. Writes result as GeoParquet to Bronze. Memory-safe: DuckDB streams results, never loads full dataset.
- `gid_classify_overture`: Loads the Overture→OSM mapping JSON. Applies category translation. Normalizes columns to unified schema. Writes Silver GeoParquet.

#### W-02: `gid_foursquare.yaml`

Same pattern as W-01. Key differences:
- `gid_fetch_foursquare`: DuckDB query against Foursquare S3 Parquet. S3 paths obtained from documented API endpoint (NOT HTML scraping — if no stable API exists, paths are maintained as config in the repo).
- `gid_classify_foursquare`: Applies Foursquare→OSM mapping JSON.

#### W-03: `gid_alltheplaces.yaml`

```yaml
nodes:
  fetch_alltheplaces:
    type: task
    handler: gid_fetch_alltheplaces
    # Downloads output.zip from data.alltheplaces.xyz/runs/latest/
    # Uses structured API/redirect, not HTML scraping
    # Output: ZIP file in Bronze

  process_alltheplaces:
    type: task
    handler: gid_process_alltheplaces
    depends_on: [fetch_alltheplaces]
    receives:
      zip_path: "fetch_alltheplaces.result.output_path"
    # Extracts ZIP, iterates GeoJSON files, merges into single DataFrame
    # Normalizes to unified schema
    # Output: Silver GeoParquet
```

#### W-04: `gid_opencellid.yaml`

```yaml
nodes:
  fetch_opencellid:
    type: task
    handler: gid_fetch_opencellid
    params: [ocid_token]
    # Downloads cell_towers.csv.gz (token-authenticated)
    # Output: CSV.GZ in Bronze

  process_opencellid:
    type: task
    handler: gid_process_opencellid
    depends_on: [fetch_opencellid]
    receives:
      csv_path: "fetch_opencellid.result.output_path"
    params: [country_filter]
    # DuckDB reads CSV.GZ, filters to LMIC countries via MCC codes
    # Wikipedia MCC table maintained as repo config (NOT scraped)
    # Normalizes to unified schema
    # Output: Silver GeoParquet
```

#### W-05: `gid_portswatch.yaml`

```yaml
nodes:
  fetch_portswatch:
    type: task
    handler: gid_fetch_portswatch
    # Paginated ArcGIS REST FeatureServer query (3 pages, 2000 records each)
    # Output: GeoParquet in Bronze

  process_portswatch:
    type: task
    handler: gid_process_portswatch
    depends_on: [fetch_portswatch]
    receives:
      data_path: "fetch_portswatch.result.output_path"
    # Normalizes to unified schema
    # Output: Silver GeoParquet
```

#### W-06 through W-10: GEM Tracker Workflows

Five separate workflows, one per GEM dataset. All follow the same pattern:

```yaml
# Template for all GEM workflows (W-06 through W-10)
nodes:
  load_gem_data:
    type: task
    handler: gid_load_gem_{type}  # e.g., gid_load_gem_power, gid_load_gem_cement
    params: [bronze_path]
    # Reads Excel from Bronze (specific sheet + columns per tracker)
    # Filters to LMIC countries
    # Normalizes to unified schema
    # Output: Silver GeoParquet
```

| Workflow | Handler | Excel Sheet | Key Columns |
|----------|---------|-------------|-------------|
| W-06: `gid_gem_power.yaml` | `gid_load_gem_power` | Sheet 2 | Lat, Lon, Country, Fuel, Capacity (MW), Status |
| W-07: `gid_gem_cement.yaml` | `gid_load_gem_cement` | "Plant Data" | Lat, Lon, Country, Plant Name, Capacity |
| W-08: `gid_gem_iron.yaml` | `gid_load_gem_iron` | "Main Data" | Lat, Lon, Country, Mine Name, Type |
| W-09: `gid_gem_chemicals.yaml` | `gid_load_gem_chemicals` | "Plant data" | Lat, Lon, Country, Plant Name, Product |
| W-10: `gid_gem_steel.yaml` | `gid_load_gem_steel` | "Plant data" + "Plant capacities" (joined) | Lat, Lon, Country, Plant Name, Capacity, Status |

#### W-11: `gid_ogim.yaml`

```yaml
nodes:
  fetch_ogim:
    type: task
    handler: gid_fetch_ogim
    # Zenodo API: GET /api/records/7466757/versions/latest → download GPKG
    # Output: GPKG in Bronze

  process_ogim_points:
    type: task
    handler: gid_process_ogim_points
    depends_on: [fetch_ogim]
    receives:
      gpkg_path: "fetch_ogim.result.output_path"
    # Reads point layers (wells, refineries, platforms, etc.)
    # Normalizes to unified schema
    # Output: Silver GeoParquet (points)

  process_ogim_lines:
    type: task
    handler: gid_process_ogim_lines
    depends_on: [fetch_ogim]
    receives:
      gpkg_path: "fetch_ogim.result.output_path"
    # Reads "Oil_Natural_Gas_Pipelines" layer
    # Output: Silver GeoParquet (lines) — used in line aggregation
```

#### W-12: `gid_egm_grid.yaml`

```yaml
nodes:
  fetch_egm:
    type: task
    handler: gid_fetch_egm_grid
    # Zenodo API: GET /api/records/3369106/versions/latest → download grid.gpkg
    # Output: GPKG in Bronze

  process_egm:
    type: task
    handler: gid_process_egm_grid
    depends_on: [fetch_egm]
    receives:
      gpkg_path: "fetch_egm.result.output_path"
    # Reads power grid lines from GPKG
    # Output: Silver GeoParquet (lines) — used in line aggregation
```

#### W-13: `gid_overture_transport.yaml`

```yaml
nodes:
  fetch_roads:
    type: task
    handler: gid_fetch_overture_transport_roads
    params: [overture_release]
    # DuckDB → S3 Parquet, filters road classes: motorway, trunk, primary, secondary, tertiary
    # Output: Parquet in Bronze (road_segments.parquet)

  fetch_rail:
    type: task
    handler: gid_fetch_overture_transport_rail
    params: [overture_release]
    # DuckDB → S3 Parquet, type=rail
    # Output: Parquet in Bronze (rail_segments.parquet)

  fetch_water:
    type: task
    handler: gid_fetch_overture_transport_water
    params: [overture_release]
    # DuckDB → S3 Parquet, type=water
    # Output: Parquet in Bronze (water_segments.parquet)
```

All three fetch nodes run in parallel (no dependencies between them).

#### W-14: `gid_solar_assets.yaml`

```yaml
nodes:
  load_solar:
    type: task
    handler: gid_load_solar_assets
    params: [bronze_path]
    # Reads CSV from Bronze, filters lat/lon validity
    # Normalizes to unified schema (main_cat = "power_plant_small" or similar)
    # Output: Silver GeoParquet
```

#### W-15: `gid_itu_nodes.yaml`

```yaml
nodes:
  load_itu:
    type: task
    handler: gid_load_itu_nodes
    params: [bronze_path]
    # Reads GeoJSON from Bronze
    # Normalizes to unified schema (main_cat = "communications_network")
    # Output: Silver GeoParquet
```

#### W-16: `gid_ozm_zones.yaml`

```yaml
nodes:
  load_ozm:
    type: task
    handler: gid_load_ozm_zones
    params: [bronze_path]
    # Reads CSV from Bronze
    # Normalizes to unified schema (main_cat = "SEZ")
    # Output: Silver GeoParquet
```

#### W-17: `gid_osm_classified.yaml` (Depends on SPIKE-01)

```yaml
# Structure TBD pending SPIKE-01 outcome
# Will follow one of:
#   A) Overture-only (if gap analysis shows sufficient coverage)
#   B) Overture + ohsome API for gap categories
#   C) Overture + lightweight Parquet extracts
#
# Classification step uses osmclass via R subprocess:
nodes:
  fetch_osm_data:
    type: task
    handler: gid_fetch_osm  # Implementation depends on SPIKE-01
    params: [country_filter]

  classify_osm:
    type: task
    handler: gid_classify_osm_r
    depends_on: [fetch_osm_data]
    receives:
      data_path: "fetch_osm_data.result.output_path"
    # Calls Rscript subprocess with osmclass
    # Input: GeoParquet (points, lines, multipolygons)
    # Output: Classified Silver GeoParquet
```

### Tier 2: Combination Workflows (Depend on Tier 1 Outputs)

#### W-20: `gid_combine_points.yaml`

```yaml
workflow: gid_combine_points
parameters:
  silver_prefix: {type: str, required: true, default: "silver/gid/"}

nodes:
  list_point_sources:
    type: task
    handler: gid_list_silver_point_sources
    params: [silver_prefix]
    # Scans Silver storage for all gid_*_points.parquet files
    # Returns list of paths

  combine_points:
    type: task
    handler: gid_combine_point_sources
    depends_on: [list_point_sources]
    receives:
      source_paths: "list_point_sources.result.paths"
    # DuckDB reads all Silver GeoParquet point files
    # Validates unified schema compliance (all 16 columns present)
    # Row-binds into single combined dataset
    # Deduplication pass (geohash-based, matching original logic)
    # Output: Silver GeoParquet (points_combined.parquet)

  load_postgis:
    type: task
    handler: gid_load_points_postgis
    depends_on: [combine_points]
    receives:
      combined_path: "combine_points.result.output_path"
    # Loads combined points into PostGIS table: silver.gid_points_combined
    # Creates spatial index on geometry
    # Output: row count, table name
```

#### Lines: No Combination Workflow Needed

Line sources (Overture transport, EGM grid, OGIM pipelines) have different schemas and are aggregated separately in the hex aggregation step. Unlike points, they are NOT row-bound into a single file — the `gid_aggregate_lines_h3` handler reads each line source independently and computes per-hex lengths by type.

### Tier 3: Aggregation Workflows (Depend on Tier 2)

#### W-30: `gid_aggregate_hex.yaml`

```yaml
workflow: gid_aggregate_hex
parameters:
  h3_resolution: {type: int, required: false, default: 6}

nodes:
  build_h3_grid:
    type: task
    handler: gid_build_h3_land_grid
    params: [h3_resolution]
    # Generates H3 Res 6 hex grid for global land areas
    # Uses landcover raster from Bronze to filter ocean-only hexes
    # Output: Silver GeoParquet (h3_land_grid.parquet) with columns:
    #   h3_index, lon_deg, lat_deg, area_m2, geometry

  aggregate_points:
    type: task
    handler: gid_aggregate_points_h3
    depends_on: [build_h3_grid]
    receives:
      grid_path: "build_h3_grid.result.output_path"
    params: [h3_resolution]
    # Reads points_combined.parquet from Silver
    # Computes H3 index for each point: h3.latlng_to_cell(lat, lon, res)
    # Pivots: count per h3_index per main_cat
    # Output columns: h3_index, pt_education_essential, pt_health_essential, pt_power_plant_large, ...
    # Output: Silver GeoParquet (points_by_hex.parquet)

  aggregate_lines:
    type: task
    handler: gid_aggregate_lines_h3
    depends_on: [build_h3_grid]
    receives:
      grid_path: "build_h3_grid.result.output_path"
    params: [h3_resolution]
    # Reads line sources from Silver:
    #   - Overture road/rail/water segment parquets
    #   - EGM power grid GeoParquet
    #   - OGIM pipeline GeoParquet
    # For each line source:
    #   - Compute H3 cells that each line intersects (h3.polygon_to_cells or line discretization)
    #   - Compute line length (meters) per hex cell
    #   - Tiered spatial processing for memory safety (matching original strategy):
    #     Process in geographic tiles, then merge
    # Output columns: h3_index, overture_road_motorway_len, overture_road_trunk_len, ...,
    #   overture_rail_len, overture_water_len, egm_grid_len, ogim_pipeline_len
    # Output: Silver GeoParquet (lines_by_hex.parquet)

  combine_hex:
    type: task
    handler: gid_combine_hex_grids
    depends_on: [aggregate_points, aggregate_lines]
    receives:
      points_hex_path: "aggregate_points.result.output_path"
      lines_hex_path: "aggregate_lines.result.output_path"
      grid_path: "build_h3_grid.result.output_path"
    # Full outer join on h3_index
    # Zero-fill NaN values
    # Join with grid metadata (lon_deg, lat_deg, area_m2, geometry)
    # Output: Silver GeoParquet (infrastructure_hex_h3r6.parquet)

  load_postgis:
    type: task
    handler: gid_load_hex_postgis
    depends_on: [combine_hex]
    receives:
      combined_path: "combine_hex.result.output_path"
    # Loads into PostGIS table: silver.gid_hex_combined
    # Creates H3 index column + spatial index
    # Output: row count, table name

  register_stac:
    type: task
    handler: gid_register_stac
    depends_on: [combine_hex, load_postgis]
    receives:
      parquet_path: "combine_hex.result.output_path"
      table_name: "load_postgis.result.table_name"
    # Registers hex grid as a STAC item/collection
    # Links to both GeoParquet asset and PostGIS table
```

### Tier 4: Master Coordinator (Optional)

#### W-40: `gid_master.yaml`

A top-level workflow that orchestrates the full pipeline end-to-end. This is optional — individual workflows can be run independently.

```yaml
workflow: gid_master
parameters:
  overture_release: {type: str, required: true}
  h3_resolution: {type: int, required: false, default: 6}
  ocid_token: {type: str, required: true}

nodes:
  # --- Tier 1: Parallel source fetches ---
  overture_places:
    type: task
    handler: gid_submit_workflow
    params: {workflow: gid_overture_places, overture_release: "{{ overture_release }}"}

  foursquare:
    type: task
    handler: gid_submit_workflow
    params: {workflow: gid_foursquare}

  alltheplaces:
    type: task
    handler: gid_submit_workflow
    params: {workflow: gid_alltheplaces}

  # ... (all Tier 1 workflows in parallel) ...

  # --- Tier 2: Combination (after all Tier 1 complete) ---
  combine_points:
    type: task
    handler: gid_submit_workflow
    depends_on: [overture_places, foursquare, alltheplaces, opencellid, portswatch,
                 gem_power, gem_cement, gem_iron, gem_chemicals, gem_steel,
                 ogim, solar_assets, itu_nodes, ozm_zones, osm_classified]
    params: {workflow: gid_combine_points}

  # --- Tier 3: Aggregation (after combination) ---
  aggregate:
    type: task
    handler: gid_submit_workflow
    depends_on: [combine_points, overture_transport, egm_grid]
    params: {workflow: gid_aggregate_hex, h3_resolution: "{{ h3_resolution }}"}
```

**Note**: The master workflow uses a `gid_submit_workflow` meta-handler that submits child workflows and monitors completion. This leverages the existing DAG Brain's ability to manage concurrent workflow runs.

---

## Handler Inventory

### New Handlers Required

| Handler | Type | Dependencies | Notes |
|---------|------|-------------|-------|
| **Fetch handlers** | | | |
| `gid_load_country_filter` | Python | `wbstats` equiv / static JSON | Loads LMIC country list + bounding boxes |
| `gid_fetch_overture_places` | Python | `duckdb` | S3 Parquet query, LMIC-filtered |
| `gid_fetch_overture_categories` | Python | `requests` | GitHub raw CSV download |
| `gid_fetch_foursquare` | Python | `duckdb` | S3 Parquet query |
| `gid_fetch_alltheplaces` | Python | `requests`, `zipfile` | REST download of output.zip |
| `gid_fetch_opencellid` | Python | `requests` | Token-authenticated CSV.GZ |
| `gid_fetch_portswatch` | Python | `requests` | Paginated ArcGIS REST query |
| `gid_fetch_ogim` | Python | `requests` | Zenodo API → GPKG download |
| `gid_fetch_egm_grid` | Python | `requests` | Zenodo API → GPKG download |
| `gid_fetch_overture_transport_roads` | Python | `duckdb` | S3 Parquet, filtered road classes |
| `gid_fetch_overture_transport_rail` | Python | `duckdb` | S3 Parquet |
| `gid_fetch_overture_transport_water` | Python | `duckdb` | S3 Parquet |
| `gid_fetch_osm` | Python | TBD (SPIKE-01) | OSM data access — method TBD |
| **Process handlers** | | | |
| `gid_process_alltheplaces` | Python | `geopandas`, `pandas` | ZIP → GeoJSON → GeoParquet |
| `gid_process_opencellid` | Python | `duckdb` | CSV.GZ → filtered GeoParquet |
| `gid_process_portswatch` | Python | `geopandas` | Schema normalization |
| `gid_process_ogim_points` | Python | `geopandas`, `fiona` | GPKG point layers → GeoParquet |
| `gid_process_ogim_lines` | Python | `geopandas`, `fiona` | GPKG pipeline layer → GeoParquet |
| `gid_process_egm_grid` | Python | `geopandas`, `fiona` | GPKG → GeoParquet |
| **Classification handlers** | | | |
| `gid_classify_overture` | Python | mapping JSON | Overture→OSM category mapping |
| `gid_classify_foursquare` | Python | mapping JSON | Foursquare→OSM category mapping |
| `gid_classify_osm_r` | Python+R | `subprocess`, `osmclass` R pkg | Rscript subprocess, data via GeoParquet |
| **Load handlers (static Bronze sources)** | | | |
| `gid_load_gem_power` | Python | `openpyxl` | Excel → unified schema → GeoParquet |
| `gid_load_gem_cement` | Python | `openpyxl` | Excel → unified schema → GeoParquet |
| `gid_load_gem_iron` | Python | `openpyxl` | Excel → unified schema → GeoParquet |
| `gid_load_gem_chemicals` | Python | `openpyxl` | Excel → unified schema → GeoParquet |
| `gid_load_gem_steel` | Python | `openpyxl` | Excel → unified schema → GeoParquet |
| `gid_load_solar_assets` | Python | `pandas` | CSV → unified schema → GeoParquet |
| `gid_load_itu_nodes` | Python | `geopandas` | GeoJSON → unified schema → GeoParquet |
| `gid_load_ozm_zones` | Python | `pandas` | CSV → unified schema → GeoParquet |
| **Combination handlers** | | | |
| `gid_list_silver_point_sources` | Python | blob storage client | Scan Silver for point GeoParquets |
| `gid_list_silver_line_sources` | Python | blob storage client | Scan Silver for line GeoParquets |
| `gid_combine_point_sources` | Python | `duckdb` | Row-bind all point GeoParquets |
| `gid_load_points_postgis` | Python | `sqlalchemy`, `geopandas` | GeoParquet → PostGIS table |
| **Aggregation handlers** | | | |
| `gid_build_h3_land_grid` | Python | `h3`, `rasterio` | H3 grid generation + ocean filtering |
| `gid_aggregate_points_h3` | Python | `h3`, `duckdb` | Point → H3 cell → pivot counts |
| `gid_aggregate_lines_h3` | Python | `h3`, `shapely`, `duckdb` | Line → H3 intersections → lengths |
| `gid_combine_hex_grids` | Python | `duckdb` | Outer join points + lines hex tables |
| `gid_load_hex_postgis` | Python | `sqlalchemy`, `geopandas` | GeoParquet → PostGIS table |
| `gid_register_stac` | Python | existing STAC handlers | STAC collection + item registration |
| **Meta handlers** | | | |
| `gid_submit_workflow` | Python | DAG Brain API | Submit child workflow, monitor completion |

**Total: ~40 new handlers**

### Existing Handlers to Reuse

| Existing Handler | Reuse For |
|-----------------|-----------|
| `stac_register_collection` | GID STAC collection creation |
| `stac_materialize_item` | GID STAC item registration |
| `blob_download_to_mount` | Bronze → mount copy |
| `blob_upload_from_mount` | Mount → Silver upload |

---

## Docker Image Changes

### R Runtime Addition

```dockerfile
# Add to existing Dockerfile after Python dependencies

# --- R runtime (r2u binary packages) ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common dirmngr wget \
    && wget -q -O- https://eddelbuettel.github.io/r2u/assets/dirk_eddelbuettel.asc \
       | tee /etc/apt/trusted.gpg.d/cranapt_key.asc \
    && echo "deb [arch=amd64] https://r2u.stat.illinois.edu/ubuntu noble main" \
       > /etc/apt/sources.list.d/cranapt.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
       r-base-core \
       r-cran-sf r-cran-s2 r-cran-data.table r-cran-collapse \
    && Rscript -e "install.packages('osmclass', repos='https://cloud.r-project.org')" \
    && rm -rf /var/lib/apt/lists/*
```

**Size impact**: ~300-400 MB added to image.

**Justification**: Required for `osmclass` classification — the author's core intellectual contribution. Python port is a documented future path but not a blocker.

### Python Dependencies Addition

```
# Add to requirements.txt
h3>=4.0
duckdb>=1.0
openpyxl>=3.1
rasterio>=1.3
```

(`geopandas`, `shapely`, `fiona`, `pandas`, `requests`, `sqlalchemy` are already in the image)

---

## Database Schema

### New PostGIS Tables

```sql
-- Combined points from all sources
CREATE TABLE IF NOT EXISTS silver.gid_points_combined (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    geom GEOMETRY(Point, 4326) NOT NULL,
    ref TEXT,
    name TEXT,
    address TEXT,
    source_orig TEXT,
    main_cat TEXT NOT NULL,
    main_tag TEXT,
    main_tag_value TEXT,
    alt_cats TEXT,
    alt_tags_values TEXT,
    other_tags_values TEXT,
    variable TEXT,
    value DOUBLE PRECISION,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gid_points_geom ON silver.gid_points_combined USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_gid_points_cat ON silver.gid_points_combined (main_cat);
CREATE INDEX IF NOT EXISTS idx_gid_points_source ON silver.gid_points_combined (source);

-- Hex-aggregated infrastructure (final output)
CREATE TABLE IF NOT EXISTS silver.gid_hex_combined (
    h3_index TEXT PRIMARY KEY,
    h3_resolution INTEGER NOT NULL DEFAULT 6,
    lon_deg DOUBLE PRECISION NOT NULL,
    lat_deg DOUBLE PRECISION NOT NULL,
    area_m2 DOUBLE PRECISION NOT NULL,
    geom GEOMETRY(Polygon, 4326) NOT NULL,

    -- Point counts by category (dynamic columns — representative sample)
    pt_education_essential INTEGER DEFAULT 0,
    pt_education_other INTEGER DEFAULT 0,
    pt_health_essential INTEGER DEFAULT 0,
    pt_health_other INTEGER DEFAULT 0,
    pt_power_plant_large INTEGER DEFAULT 0,
    pt_power_plant_small INTEGER DEFAULT 0,
    pt_power_other INTEGER DEFAULT 0,
    pt_communications_network INTEGER DEFAULT 0,
    pt_financial INTEGER DEFAULT 0,
    pt_food INTEGER DEFAULT 0,
    pt_industrial INTEGER DEFAULT 0,
    pt_mining INTEGER DEFAULT 0,
    pt_port INTEGER DEFAULT 0,
    pt_public_transport INTEGER DEFAULT 0,
    pt_transport_infrastructure INTEGER DEFAULT 0,
    pt_commercial INTEGER DEFAULT 0,
    -- ... (full list derived from SPIKE-02/03 taxonomy extraction)

    -- Line lengths by type (meters)
    overture_road_motorway_len DOUBLE PRECISION DEFAULT 0,
    overture_road_trunk_len DOUBLE PRECISION DEFAULT 0,
    overture_road_primary_len DOUBLE PRECISION DEFAULT 0,
    overture_road_secondary_len DOUBLE PRECISION DEFAULT 0,
    overture_road_tertiary_len DOUBLE PRECISION DEFAULT 0,
    overture_rail_len DOUBLE PRECISION DEFAULT 0,
    overture_water_len DOUBLE PRECISION DEFAULT 0,
    egm_grid_len DOUBLE PRECISION DEFAULT 0,
    ogim_pipeline_len DOUBLE PRECISION DEFAULT 0,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gid_hex_geom ON silver.gid_hex_combined USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_gid_hex_h3 ON silver.gid_hex_combined (h3_index);
```

**Note**: The exact `pt_*` columns will be finalized after SPIKE-02/03 produce the complete taxonomy. The table creation handler should generate columns dynamically from the taxonomy config rather than hardcoding them.

---

## Memory & Performance Constraints

### 8GB RAM Budget

| Operation | Memory Strategy |
|-----------|----------------|
| DuckDB S3 Parquet queries | Streaming — DuckDB manages memory internally, configurable via `SET memory_limit='4GB'` |
| OSM classification (R subprocess) | Process per-country or in chunks. R process is isolated — OOM kills R, not Python worker |
| AllThePlaces ZIP processing | Stream GeoJSON files from ZIP, don't extract all to disk |
| Line aggregation (H3 intersections) | Tiered geographic processing (original uses 0.25° → 1° → 4° → 16° tiles). Replicate this. |
| Point combination (row-bind) | DuckDB `UNION ALL` across Parquet files — never loads all into memory |
| OpenCellID (millions of cell towers) | DuckDB reads CSV.GZ with streaming, filter early |

### Estimated Data Volumes

| Dataset | Approximate Size | Post-LMIC-Filter |
|---------|-----------------|------------------|
| Overture Places (global) | ~72M rows | ~30-40M rows |
| Foursquare Places | ~50M rows | ~20-30M rows |
| OpenCellID | ~50M rows | ~20-30M rows |
| OSM (all LMICs) | ~100M features | varies by category |
| Overture Transportation | ~200M segments | ~80-100M segments |
| GEM trackers (all 5) | ~50K rows total | ~30K rows |
| Final hex grid (H3 R6) | ~5M land hexes | ~3M LMIC hexes |

---

## Configuration Files

### Repo-Checked Config

```
config/gid/
├── lmic_countries.json          # Country list + ISO codes + bounding boxes
├── mcc_country_codes.json       # Mobile Country Codes for OpenCellID filtering
├── taxonomy/
│   ├── osmclass_categories.json # Extracted from R osmclass package (SPIKE-02)
│   ├── overture_to_osm.json     # Overture→OSM category mapping (SPIKE-03)
│   └── foursquare_to_osm.json   # Foursquare→OSM category mapping (SPIKE-03)
├── sources/
│   ├── foursquare_s3_paths.json # S3 paths for Foursquare data (maintained manually)
│   └── alltheplaces_url.json    # Download URL config (no HTML scraping)
└── r_scripts/
    └── classify_osm.R           # R script called via subprocess for osmclass
```

### Bronze Blob Layout

```
bronze/gid/
├── overture/
│   ├── places/                  # Fetched Overture places GeoParquet
│   ├── categories/              # Overture category taxonomy
│   └── transportation/
│       ├── road_segments.parquet
│       ├── rail_segments.parquet
│       └── water_segments.parquet
├── foursquare/
│   └── places/                  # Fetched Foursquare places GeoParquet
├── alltheplaces/
│   ├── output.zip               # Raw download
│   └── alltheplaces.parquet     # Processed
├── opencellid/
│   └── cell_towers.csv.gz
├── portswatch/
│   └── portswatch.parquet
├── gem/
│   ├── global-integrated-power.xlsx
│   ├── cement-concrete.xlsx
│   ├── iron-ore-mines.xlsx
│   ├── chemicals-inventory.xlsx
│   └── iron-steel.xlsx
├── ogim/
│   └── OGIM.gpkg
├── egm/
│   └── grid.gpkg
├── sam/
│   └── solar-assets.csv
├── itu/
│   └── node-ties.geojson
├── ozm/
│   └── open-zone-map.csv
└── landcover/
    └── open-water.tif
```

### Silver Blob Layout

```
silver/gid/
├── points/
│   ├── overture_places.parquet
│   ├── foursquare_places.parquet
│   ├── alltheplaces.parquet
│   ├── opencellid.parquet
│   ├── portswatch.parquet
│   ├── gem_power.parquet
│   ├── gem_cement.parquet
│   ├── gem_iron.parquet
│   ├── gem_chemicals.parquet
│   ├── gem_steel.parquet
│   ├── ogim_points.parquet
│   ├── solar_assets.parquet
│   ├── itu_nodes.parquet
│   ├── ozm_zones.parquet
│   └── osm_classified.parquet   # (post SPIKE-01)
├── lines/
│   ├── overture_roads.parquet
│   ├── overture_rail.parquet
│   ├── overture_water.parquet
│   ├── egm_grid.parquet
│   └── ogim_pipelines.parquet
├── combined/
│   └── points_combined.parquet
├── hex/
│   ├── h3_land_grid.parquet
│   ├── points_by_hex.parquet
│   ├── lines_by_hex.parquet
│   └── infrastructure_hex_h3r6.parquet  # FINAL OUTPUT
└── stac/
    └── gid_collection.json
```

---

## Testing Strategy

### Unit Tests (per handler)

Each handler gets a test with small fixture data:
- Verify schema compliance (16-column output for point handlers)
- Verify category mapping correctness (spot-check known mappings)
- Verify H3 assignment for known lat/lon points

### Integration Tests (per workflow)

- Submit each workflow with a small country subset (e.g., 2-3 small LMIC countries)
- Verify Bronze → Silver → PostGIS data flow
- Verify row counts are non-zero and reasonable

### End-to-End Test

- Run `gid_master.yaml` with a minimal country set
- Verify final `infrastructure_hex_h3r6.parquet` has both point and line columns
- Verify PostGIS tables are queryable
- Verify STAC item is discoverable

### R Classification Validation

- Run `osmclass` via R subprocess on a known test dataset
- Compare output categories against expected values from the original R pipeline
- This is the critical fidelity check — the taxonomy must match

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| OSM access pattern unclear (SPIKE-01) | Blocks W-17 | Overture covers most OSM data. Spike resolves before implementation. Other 16 workflows proceed independently. |
| R subprocess adds image size | +300-400 MB | Acceptable for `osmclass` fidelity. Python port is the documented exit strategy. |
| Overture S3 schema changes between releases | Breaks fetch handlers | Pin Overture release version as workflow parameter. Handler validates expected columns. |
| DuckDB memory on large S3 queries | OOM on 8GB worker | `SET memory_limit='4GB'` + streaming. Test with largest source (Overture Places) first. |
| Line aggregation is computationally expensive | Long-running tasks | Tiered geographic processing. Consider multiple workers. Janitor timeout must be generous (hours, not minutes). |
| Category taxonomy drift if upstream sources change | Misclassification | Taxonomy configs are versioned in repo. Category validation in combination step flags unknown categories. |
| AllThePlaces download URL may change | Fetch failure | URL maintained in config file, not hardcoded. Handler logs clear error on 404. |
| GEM Excel sheet names may change between releases | Load failure | Sheet names in handler config, not hardcoded. Handler logs clear error on missing sheet. |

---

## Implementation Order

### Phase 0: Spikes (Resolve Before Implementation)
1. SPIKE-01: OSM-vs-Overture gap analysis
2. SPIKE-02: `osmclass` taxonomy extraction to JSON
3. SPIKE-03: Overture/Foursquare mapping extraction to JSON/YAML

### Phase 1: Foundation
1. Country filter config (`lmic_countries.json`)
2. Docker image update (r2u + R packages + Python deps)
3. Unified schema validation utility
4. `gid_load_country_filter` handler

### Phase 2: Simple Sources (Low Risk, Validate Pattern)
1. GEM workflows (W-06 through W-10) — simplest: read Excel, normalize, write GeoParquet
2. Static source workflows (W-14 Solar, W-15 ITU, W-16 OZM)
3. PortWatch (W-05) — single REST API

### Phase 3: DuckDB Sources (Core Pattern)
1. Overture Places (W-01) — establishes DuckDB + S3 pattern
2. Foursquare (W-02) — same pattern, different source
3. OpenCellID (W-04) — DuckDB reads CSV.GZ
4. Overture Transportation (W-13) — DuckDB, line data

### Phase 4: Complex Sources
1. AllThePlaces (W-03) — ZIP + GeoJSON processing
2. OGIM (W-11) — GPKG with multiple layers (points + lines)
3. EGM Grid (W-12) — GPKG, line data
4. OSM Classified (W-17) — depends on SPIKE-01 resolution

### Phase 5: Combination + Aggregation
1. Combine Points (W-20) — row-bind all Silver point GeoParquets
2. H3 Land Grid generation
3. Point aggregation (W-30 partial)
4. Line aggregation (W-30 partial) — most complex, tiered processing
5. Final hex combination + PostGIS load + STAC registration

### Phase 6: Master Workflow
1. `gid_master.yaml` — ties everything together
2. End-to-end test with minimal country set

---

## Open Questions

1. **Foursquare S3 access** — The original scrapes HTML docs for S3 paths. Need to determine if Foursquare provides a stable API or if we maintain S3 paths as config.
2. **AllThePlaces URL stability** — Is `data.alltheplaces.xyz/runs/latest/` a stable redirect? Or do we need to query their API?
3. **OpenCellID token management** — Token is in the original source code. Should we treat it as a secret in Azure Key Vault?
4. **GEM data refresh cadence** — GEM publishes quarterly. Should workflows auto-detect new versions, or is manual Bronze upload acceptable?
5. **Line aggregation parallelism** — The tiered spatial processing is single-threaded in the original. Should we fan-out by geographic tile for parallel processing?
6. **PostGIS table versioning** — Should hex grid tables be versioned (e.g., `gid_hex_combined_v1`, `gid_hex_combined_v2`) or overwritten in place?
