# Global Infrastructure Database (GID) Pipeline Design Spec

**Date**: 28 MAR 2026
**Status**: Draft (Rev 3)
**Author**: Robert + Claude Prime
**Source Repo**: https://github.com/SebKrantz/Global-Infrastructure-Database
**Source Author**: Sebastian Krantz

---

## Purpose

Replicate the Global Infrastructure Database pipeline as a single DAG workflow in our orchestration system. The original pipeline (R `targets` + 2 Python scripts) aggregates infrastructure data from 18+ sources across all low- and middle-income countries (LMICs), harmonizes ~60 infrastructure categories, and produces a unified hexagonal grid dataset.

Our implementation: ~14 parameterized Python handlers (with R subprocess for `osmclass` classification), DuckDB + GeoParquet as the data backbone, PostGIS as the live combine target (no in-memory rowbind), SQL-based H3 Res 6 hex aggregation, and a single 13-node DAG workflow.

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
- PBF → GeoParquet conversion via `ogr2ogr -f Parquet` (no GPKG intermediate)

### Out of Scope

- Data sources mentioned in `DATA.md` but not yet implemented (SFI GeoAsset, GRIP roads, OOKLA, AfterFibre, etc.) — these become future workflow additions using the same patterns
- Frontend visualization (existing OGC Features API / TiPG serves the data)
- Scheduling (existing DAGScheduler handles periodic re-runs once workflows exist)
- Cross-source deduplication (see note below)

### Cross-Source Deduplication Caveat

There is currently NO cross-source deduplication in Sebastian's pipeline. The same physical hospital can appear as an OSM node, an Overture place, and a Foursquare place — all three records make it to the final output. This is a known limitation, not a bug. Downstream consumers should understand that hex cell counts may include duplicates across sources.

### Spikes (Investigation Required Before Implementation)

- **SPIKE-01: OSM-vs-Overture gap analysis** — Determine which OSM infrastructure categories are NOT covered by Overture Places/Transportation. The PBF→GeoParquet path (Section 7) handles the OSM data access, but the spike determines whether we need ALL country PBFs or can supplement with Overture. Acceptance criteria: documented category gap matrix + recommended country set + memory profile under 8GB.
- **SPIKE-02: osmclass mapping extraction** — Extract the complete classification dictionary from the `osmclass` R package as a JSON file. Verify completeness against the R package source. This JSON serves as the authoritative taxonomy reference regardless of whether classification runs in R or Python. **Critical secondary output**: the exhaustive list of OSM tag keys referenced anywhere in the classification rules. This list mechanically generates the DuckDB WHERE clause for OSM filtering (see Section 7, Step 3) — no human judgment, no risk of missing tags.
- **SPIKE-03: Overture/Foursquare mapping extraction** — Extract the 46KB `overture_foursquares_to_osm_det.R` mapping table into a structured JSON/YAML config. Verify category coverage against original.

---

## Core Data Flow

The revised pipeline follows this pattern for ALL data, including OSM:

```
PBF (on Azure Files mount)
  → ogr2ogr -f Parquet (streams, low memory, no intermediate GPKG)
    → GeoParquet on mount (per country, per layer)
      → DuckDB query with predicate pushdown (only classification-relevant rows enter memory)
        → osmclass classification (runs on filtered subset, ~5-10% of original data)
          → INSERT into PostGIS (append per source, no in-memory combine)
            → H3 aggregation via SQL (server-side, never loads 100M rows into Python)
```

**Key points:**

- **Azure Files mount is the working storage.** PBFs download there, GeoParquet intermediate files live there, DuckDB reads from there.
- **GPKG is eliminated entirely.** PBF converts directly to GeoParquet via `ogr2ogr -f Parquet`.
- **The in-memory combine step is eliminated.** Each source's normalized output is `INSERT`ed/appended to `silver.gid_points_combined` in PostGIS. The table IS the combined dataset.
- **H3 aggregation becomes a PostGIS/SQL query**, not an in-memory R/Python operation.
- **Peak RAM at any point: ~2-4GB** (one country's filtered features for the largest OSM country).

---

## Architecture Overview

### Design Principles

1. **Single DAG, not a workflow-per-source** — One 13-node workflow. Sources that share structure share a handler via config.
2. **DuckDB + GeoParquet everywhere** — S3 Parquet queries via DuckDB, intermediate storage as GeoParquet, no PBF/QS/GPKG in the processing path.
3. **PostGIS is the combine target** — Each source handler INSERTs directly to `silver.gid_points_combined`. No in-memory rowbind.
4. **SQL-based aggregation** — H3 hex aggregation runs as PostGIS queries (h3-pg extension), not in Python/R memory.
5. **R via subprocess, not embedding** — `osmclass` runs as an Rscript subprocess. Data exchange via GeoParquet files on the mount.
6. **Copy to mount first** — Per existing project convention, all ETL copies Bronze → mount before processing. No direct cloud reads.
7. **Respect the author's taxonomy** — Classification mappings extracted as explicit, auditable config files (JSON/YAML).
8. **Config-driven handlers** — Structurally identical operations (GEM Excel files, static CSV/GeoJSON files) share one handler with YAML/JSON config per source.

### System Context

```
┌──────────────────────────────────────────────────────────────────┐
│                    DAG Brain (Orchestrator)                       │
│                                                                  │
│  gid_pipeline.yaml — single 13-node DAG                          │
│                                                                  │
│  Node 1:  Country scoping                                        │
│     ├── Node 2:  Overture Places                                 │
│     ├── Node 3:  Foursquare                                      │
│     ├── Node 4:  AllThePlaces                                    │
│     ├── Node 5:  OpenCellID                                      │
│     ├── Node 6:  Config sources (GEM×5, solar, ITU, OZM)          │
│     ├── Node 7:  OGIM (points + lines)                           │
│     ├── Node 8:  OSM PBF → GeoParquet                            │
│     │     └── Node 9:  OSM Classification                        │
│     ├── Node 10: Overture Transportation                         │
│     └── Node 11: EGM Grid                                        │
│                    │                                              │
│  Nodes 2-7,9 ──► Node 12: PostGIS health check (verify + ANALYZE) │
│                    │                                              │
│  Nodes 10,11,7,12 ──► Node 13: H3 Aggregation (SQL) + STAC      │
└───────────────────────┬──────────────────────────────────────────┘
                        │ claims READY tasks
                        ▼
┌──────────────────────────────────────────────────────────────────┐
│                    Docker Worker(s)                               │
│                                                                  │
│  Python handlers (~14):        R subprocess:                     │
│  • gid_load_country_filter     • osmclass classification         │
│  • gid_fetch_overture_places                                     │
│  • gid_fetch_foursquare        DuckDB:                           │
│  • gid_fetch_alltheplaces      • S3 Parquet queries              │
│  • gid_fetch_opencellid        • Local Parquet queries           │
│  • gid_fetch_portswatch        • H3 extension                   │
│  • gid_load_config_source                                        │
│  • gid_fetch_ogim              ogr2ogr:                          │
│  • gid_osm_pbf_to_geoparquet   • PBF → Parquet streaming        │
│  • gid_classify_osm                                              │
│  • gid_fetch_overture_transport                                  │
│  • gid_fetch_egm_grid                                            │
│  • gid_combine_to_postgis                                        │
│  • gid_aggregate_h3                                              │
└──────────────────────────────────────────────────────────────────┘
         │                           │
         ▼                           ▼
┌─────────────────┐    ┌──────────────────────────────┐
│  Azure Files    │    │  PostgreSQL (PostGIS + h3-pg) │
│  Mount          │    │                              │
│                 │    │  silver.gid_points_combined   │
│  Bronze:        │    │    (live combine target —     │
│  • raw downloads│    │     each source INSERTs)      │
│  • static Excel │    │                              │
│  • config files │    │  silver.gid_hex_combined      │
│                 │    │    (SQL-aggregated output)     │
│  Silver:        │    │                              │
│  • GeoParquet   │    │  pgstac:                      │
│  • processed    │    │  • GID collections            │
│                 │    │                              │
│  Mount work:    │    │                              │
│  • PBF files    │    │                              │
│  • ogr2ogr out  │    │                              │
└─────────────────┘    └──────────────────────────────┘
```

---

## Data Sources Inventory

### A. Remote-Fetched Sources (handlers download at runtime)

| # | Source | ID Prefix | Access Method | Format | Handler |
|---|--------|-----------|---------------|--------|---------|
| 1 | OpenStreetMap | OSM | Geofabrik PBF downloads per country (URL list in config) | PBF → GeoParquet (ogr2ogr) | `gid_osm_pbf_to_geoparquet` → `gid_classify_osm` |
| 2 | Overture Maps Places | OVP | DuckDB → S3 Parquet (`s3://overturemaps-us-west-2/release/{version}/theme=places/`) | Parquet | `gid_fetch_overture_places` |
| 3 | Foursquare OS Places | FSP | DuckDB → S3 Parquet (paths from documented API, NOT HTML scraping) | Parquet | `gid_fetch_foursquare` |
| 4 | AllThePlaces | ATP | REST API to `data.alltheplaces.xyz` (structured endpoint, not HTML scrape) | ZIP → GeoJSON → GeoParquet | `gid_fetch_alltheplaces` |
| 5 | OpenCellID | OCID | Direct URL download (token-authenticated CSV.GZ) | CSV.GZ → GeoParquet | `gid_fetch_opencellid` |
| 6 | PortWatch (IMF) | PW | ArcGIS REST FeatureServer query (paginated JSON) | GeoJSON → GeoParquet | `gid_fetch_portswatch` |
| 7 | OGIM (Oil & Gas) | OGIM | Zenodo API → latest version → GPKG download | GeoPackage → GeoParquet | `gid_fetch_ogim` |
| 8 | EGM Grid (Gridfinder) | EGM | Zenodo API → latest version → GPKG download | GeoPackage → GeoParquet | `gid_fetch_egm_grid` |
| 9 | Overture Transportation | OVT | DuckDB → S3 Parquet (`theme=transportation/type=segment/`) | Parquet | `gid_fetch_overture_transport` |

### B. Static Sources (pre-loaded to Bronze, processed by `gid_load_config_source`)

All static sources share one handler (`gid_load_config_source`) with per-source YAML config.

| # | Source | ID Prefix | Original Format | Bronze Path | Config Key |
|---|--------|-----------|-----------------|-------------|------------|
| 10 | GEM Global Integrated Power | GIP | Excel (.xlsx, sheet 2) | `bronze/gid/gem/global-integrated-power.xlsx` | `gem_power` |
| 11 | GEM Cement & Concrete | GEMCEM | Excel (.xlsx, sheet "Plant Data") | `bronze/gid/gem/cement-concrete.xlsx` | `gem_cement` |
| 12 | GEM Iron Ore Mines | GEMIRON | Excel (.xlsx, sheet "Main Data") | `bronze/gid/gem/iron-ore-mines.xlsx` | `gem_iron` |
| 13 | GEM Chemicals Inventory | GEMCHEM | Excel (.xlsx, sheet "Plant data") | `bronze/gid/gem/chemicals-inventory.xlsx` | `gem_chemicals` |
| 14 | GEM Iron & Steel | GEMSTEEL | Excel (.xlsx, sheets "Plant data" + "Plant capacities") | `bronze/gid/gem/iron-steel.xlsx` | `gem_steel` |
| 15 | TZ-SAM Solar Assets | SAM | CSV | `bronze/gid/sam/solar-assets.csv` | `solar_assets` |
| 16 | ITU Telecom Nodes | ITU | GeoJSON | `bronze/gid/itu/node-ties.geojson` | `itu_nodes` |
| 17 | Open Zone Map | OZM | CSV | `bronze/gid/ozm/open-zone-map.csv` | `ozm_zones` |
| 18 | EarthEnv Landcover | LAND | GeoTIFF | `bronze/gid/landcover/open-water.tif` | (used by H3 grid gen) |

### C. Reference/Config Data (checked into repo or Bronze)

| Item | Format | Purpose |
|------|--------|---------|
| `osmclass` taxonomy | JSON (extracted from R package — SPIKE-02) | OSM tag → infrastructure category mapping |
| Overture category mapping | JSON/YAML (extracted from R code — SPIKE-03) | Overture category → OSM category mapping |
| Foursquare category mapping | JSON/YAML (extracted from R code — SPIKE-03) | Foursquare category → OSM category mapping |
| LMIC country list | JSON (derived from World Bank API at build time) | Country filter for all sources |
| Geofabrik country URLs | JSON (maintained in repo, not scraped) | PBF download URLs per country |
| GID source configs | YAML (per-source config for `gid_load_config_source`) | Column mappings, sheet names, coord formats |
| Overture release version | Runtime parameter | Which Overture release to query |

---

## Config-Driven Source Loading

The `gid_load_config_source` handler replaces 8 separate handlers (5 GEM + solar + ITU + OZM) with a single parameterized handler. It reads a YAML config that specifies how to load and normalize each source.

**Note**: PortWatch is NOT included here despite being a "simple" source. Its paginated ArcGIS REST API fetch (3 requests at offset 0/1000/2000) is structurally different from "read a file from Bronze" and keeps its own handler (`gid_fetch_portswatch`).

### Source Config Format

```yaml
# config/gid/sources/gem_power.yaml
source_key: gem_power
id_prefix: GIP
bronze_path: bronze/gid/gem/global-integrated-power.xlsx
format: excel
sheet: 2
coord_format: columns   # lat/lon are separate columns
lat_col: latitude
lon_col: longitude
main_cat: power
main_tag: plant_type
main_tag_value_col: type
variable: capacity_mw
value_col: capacity_mw
id_template: "GIP_{gem_location_id}_{status}"
filters:
  status: [operating, construction, inactive, mothballed]

# config/gid/sources/gem_cement.yaml
source_key: gem_cement
id_prefix: GEMCEM
bronze_path: bronze/gid/gem/cement-concrete.xlsx
format: excel
sheet: "Plant Data"
coord_format: string     # single "coordinates" field: "lat, lon"
coord_col: coordinates
main_cat: industrial
main_tag: sector
main_tag_value: cement
variable: cement_capacity_millions_metric_tonnes_per_annum
value_col: cement_capacity_millions_metric_tonnes_per_annum
id_template: "GEMCEM_{gem_plant_id}"

# config/gid/sources/gem_steel.yaml — SHEET JOIN CASE
# GEM Steel requires joining two sheets before normalization.
# Sebastian's original: join(plants, caps, on = c("plant_id", "plant_name_english", ...))
source_key: gem_steel
id_prefix: GEMSTEEL
bronze_path: bronze/gid/gem/iron-steel.xlsx
format: excel
sheet: "Plant data"
join:
  sheet: "Plant capacities"
  on: [plant_id, plant_name_english]
  how: left
  columns: [nominal_crude_steel_capacity_ttpa]  # columns to bring from joined sheet
coord_format: columns
lat_col: latitude
lon_col: longitude
main_cat: industrial
main_tag: sector
main_tag_value: steel
variable: nominal_crude_steel_capacity_ttpa
value_col: nominal_crude_steel_capacity_ttpa
id_template: "GEMSTEEL_{gem_plant_id}"

# config/gid/sources/solar_assets.yaml
source_key: solar_assets
id_prefix: SAM
bronze_path: bronze/gid/sam/solar-assets.csv
format: csv
coord_format: columns
lat_col: lat
lon_col: lon
main_cat: power_plant_small
main_tag: generator:source
main_tag_value: solar
# ... etc

# config/gid/sources/itu_nodes.yaml
source_key: itu_nodes
id_prefix: ITU
bronze_path: bronze/gid/itu/node-ties.geojson
format: geojson
main_cat: communications_network
# ... etc

# config/gid/sources/ozm_zones.yaml
source_key: ozm_zones
id_prefix: OZM
bronze_path: bronze/gid/ozm/open-zone-map.csv
format: csv
coord_format: columns
lat_col: latitude
lon_col: longitude
main_cat: SEZ
# ... etc
```

The handler logic:
1. Read Bronze file per `format` (excel/csv/geojson)
2. If `join` config is present, read the secondary sheet and join on specified keys (handles GEM Steel's two-sheet pattern)
3. Parse coordinates per `coord_format` (columns vs string)
4. Apply filters if specified
5. Normalize to unified 16-column schema using column mappings
6. Write Silver GeoParquet **and** INSERT to `silver.gid_points_combined` in PostGIS

The handler loops through ALL source configs in a single invocation (Node 6 in the DAG), writing each source's normalized output to both Silver GeoParquet and PostGIS.

---

## Unified Point Schema

All point sources are normalized to this 16-column schema before insertion to PostGIS. This replicates the original exactly.

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

## DAG Workflow Definition

### Single Workflow: `gid_pipeline.yaml`

```yaml
workflow: gid_pipeline
description: "Global Infrastructure Database — full pipeline"
parameters:
  overture_release: {type: str, required: true}
  h3_resolution: {type: int, required: false, default: 6}
  ocid_token: {type: str, required: true}
  country_filter: {type: str, required: true, default: "config/gid/lmic_countries.json"}

nodes:
  # ─── Node 1: Country scoping ───
  scope_countries:
    type: task
    handler: gid_load_country_filter
    params: [country_filter]
    # Also TRUNCATEs silver.gid_points_combined before sources begin INSERTing

  # ─── Nodes 2-11: Parallel source fetches (all depend only on Node 1) ───

  overture_places:
    type: task
    handler: gid_fetch_overture_places
    depends_on: [scope_countries]
    receives:
      countries: "scope_countries.result.countries"
    params: [overture_release]

  foursquare:
    type: task
    handler: gid_fetch_foursquare
    depends_on: [scope_countries]
    receives:
      countries: "scope_countries.result.countries"

  alltheplaces:
    type: task
    handler: gid_fetch_alltheplaces
    depends_on: [scope_countries]
    receives:
      countries: "scope_countries.result.countries"

  opencellid:
    type: task
    handler: gid_fetch_opencellid
    depends_on: [scope_countries]
    receives:
      countries: "scope_countries.result.countries"
    params: [ocid_token]

  config_sources:
    type: task
    handler: gid_load_config_source
    depends_on: [scope_countries]
    receives:
      countries: "scope_countries.result.countries"
    # Loops through all source configs: GEM×5, solar, ITU, OZM
    # Each source → Silver GeoParquet + INSERT to PostGIS

  portswatch:
    type: task
    handler: gid_fetch_portswatch
    depends_on: [scope_countries]
    receives:
      countries: "scope_countries.result.countries"
    # Paginated ArcGIS REST FeatureServer (3 pages at offset 0/1000/2000)
    # Normalize + INSERT to PostGIS

  ogim:
    type: task
    handler: gid_fetch_ogim
    depends_on: [scope_countries]
    receives:
      countries: "scope_countries.result.countries"
    # Zenodo fetch + multi-layer GPKG processing (points + lines)
    # Points → PostGIS, lines → Silver GeoParquet

  osm_pbf_convert:
    type: task
    handler: gid_osm_pbf_to_geoparquet
    depends_on: [scope_countries]
    receives:
      countries: "scope_countries.result.countries"
    # Downloads PBF per country → ogr2ogr -f Parquet → GeoParquet on mount
    # Skips countries whose GeoParquet already exists (targets-style caching)
    # Deletes PBF after successful conversion
    # Estimated runtime: 12-24 hours (longest node in DAG)

  osm_classify:
    type: task
    handler: gid_classify_osm
    depends_on: [osm_pbf_convert]
    receives:
      parquet_dir: "osm_pbf_convert.result.output_dir"
    # DuckDB reads filtered rows from GeoParquet → osmclass R subprocess → PostGIS

  overture_transport:
    type: task
    handler: gid_fetch_overture_transport
    depends_on: [scope_countries]
    receives:
      countries: "scope_countries.result.countries"
    params: [overture_release]
    # Single handler, parameterized: road (by class), rail, water
    # Output: Silver GeoParquet per subtype

  egm_grid:
    type: task
    handler: gid_fetch_egm_grid
    # No country filter — global grid dataset
    # Zenodo download → GeoParquet (lines)

  # ─── Node 12: PostGIS health check (NOT data movement) ───

  combine_postgis:
    type: task
    handler: gid_combine_to_postgis
    depends_on: [overture_places, foursquare, alltheplaces, opencellid,
                 config_sources, ogim, osm_classify, portswatch]
    # This is a HEALTH CHECK, not a data movement step.
    # All sources have already INSERTed directly to silver.gid_points_combined.
    # This node:
    #   1. Verifies expected source count (all sources present)
    #   2. Verifies no source has zero rows
    #   3. Runs ANALYZE silver.gid_points_combined
    #   4. REINDEX if table was truncated and repopulated
    #   5. Logs per-source row counts for auditability

  # ─── Node 13: H3 Aggregation + STAC ───

  h3_aggregate:
    type: task
    handler: gid_aggregate_h3
    depends_on: [combine_postgis, overture_transport, egm_grid, ogim]
    params: [h3_resolution]
    # Point aggregation: SQL against silver.gid_points_combined via h3-pg
    # Line aggregation: read line GeoParquets, compute hex intersections
    # Combine: outer join points + lines on h3_index
    # Write: silver.gid_hex_combined in PostGIS
    # Register: STAC collection + item
```

### Node Dependencies (Visual)

```
Node 1 (scope_countries + TRUNCATE gid_points_combined)
  │
  ├── Node 2  (overture_places)      ──┐
  ├── Node 3  (foursquare)            ──┤
  ├── Node 4  (alltheplaces)          ──┤
  ├── Node 5  (opencellid)            ──┤
  ├── Node 6  (config_sources)        ──┤
  ├── Node 6b (portswatch)            ──┤
  ├── Node 7  (ogim) ─────────────────┼──┐
  ├── Node 8  (osm_pbf_convert)       │  │
  │     └── Node 9 (osm_classify)   ──┤  │
  ├── Node 10 (overture_transport) ───┼──┤
  └── Node 11 (egm_grid)          ───┼──┤
                                      │  │
                              Node 12 ◄┘  │
                           (health check: verify + ANALYZE)
                                      │  │
                              Node 13 ◄──┘
                           (h3_aggregate + STAC)
```

Nodes 2-11 are all independent and parallelizable. Node 12 depends on all point sources (including PortWatch). Node 13 depends on 12 plus line sources (transport, EGM, OGIM pipelines).

---

## OSM Path: PBF → GeoParquet (Detail)

This is the critical architecture change that eliminates the memory problem for OSM processing.

### Runtime Estimate

This node is the longest-running in the DAG by far. Downloading ~65GB of PBFs sequentially and converting each to three GeoParquet layers is estimated at 12-24 hours, depending on network speed and Azure Files SMB latency (which slows ogr2ogr significantly vs local SSD).

### Caching / Failure Recovery

The handler uses `targets`-style caching: skip countries whose GeoParquet files already exist on the mount. This means:
- A failed run can be restarted without re-downloading and re-converting completed countries
- If the handler is killed mid-country, only that one country's partial output needs cleanup (delete partial Parquet files, re-run)
- No need to split into separate "download" and "convert" nodes — caching handles the failure case

```python
for country in countries:
    points_path = f"/mnt/fileshare/osm/{country}-points.parquet"
    if all(os.path.exists(f"/mnt/fileshare/osm/{country}-{layer}.parquet")
           for layer in ["points", "lines", "multipolygons"]):
        log.info(f"Skipping {country} — GeoParquet already exists")
        continue
    # Download PBF, convert, delete PBF
```

### Step 1: Download PBF to mount

Sequential download of ~130 country PBFs from Geofabrik to Azure Files mount. ~65GB total. Download URLs maintained in `config/gid/geofabrik_urls.json` (NOT scraped from HTML).

### Step 2: Convert PBF → GeoParquet per layer

```bash
# Per country, per layer — can be parallelized
ogr2ogr -f Parquet /mnt/fileshare/osm/brazil-points.parquet \
  /mnt/fileshare/osm/brazil-latest.osm.pbf points

ogr2ogr -f Parquet /mnt/fileshare/osm/brazil-lines.parquet \
  /mnt/fileshare/osm/brazil-latest.osm.pbf lines

ogr2ogr -f Parquet /mnt/fileshare/osm/brazil-multipolygons.parquet \
  /mnt/fileshare/osm/brazil-latest.osm.pbf multipolygons
```

GDAL streams PBF → Parquet. Low memory. No GPKG intermediate. Delete PBF after successful conversion.

### Step 3: DuckDB query with predicate pushdown

Instead of loading 80M multipolygons into memory and classifying, query only the rows that could match any classification rule:

```sql
-- WHERE clause AUTO-GENERATED from SPIKE-02 tag key list.
-- Every tag key referenced anywhere in osmclass classification rules
-- becomes an IS NOT NULL check. This is mechanical, not manual.
-- The tag key list is a direct output of SPIKE-02 taxonomy extraction.
SELECT *
FROM '/mnt/fileshare/osm/brazil-multipolygons.parquet'
WHERE (amenity IS NOT NULL
   OR building IS NOT NULL
   OR healthcare IS NOT NULL
   OR shop IS NOT NULL
   OR tourism IS NOT NULL
   OR power IS NOT NULL
   OR industrial IS NOT NULL
   OR military IS NOT NULL
   OR railway IS NOT NULL
   OR man_made IS NOT NULL)
   -- ... (complete list from SPIKE-02 osmclass_tag_keys.json)
   -- Exclude administrative/natural features per Sebastian's logic:
   AND (boundary IS NULL OR boundary NOT IN ('administrative', 'municipality', 'political'))
   AND natural IS NULL
   AND geological IS NULL
```

The WHERE clause generation is a build-time step: read `osmclass_tag_keys.json` (SPIKE-02 output), emit the SQL predicate. If a tag key exists anywhere in the classification rules, it goes in the `IS NOT NULL` filter. No human judgment needed, no risk of missing tags.

Returns ~5-10% of original rows. For Brazil's multipolygons: ~4-8M rows instead of 80M. Easily fits in 2-4GB.

### Step 4: Classify the filtered subset

Pass the filtered rows to `osmclass` (R subprocess). This is Sebastian's exact classification logic running on exactly the same data — pre-filtered to exclude features that would have been discarded after classification anyway.

### Step 5: INSERT to PostGIS

Classified results → `INSERT INTO silver.gid_points_combined`. Per country, sequential. Memory freed between countries.

### Validation approach

Run both paths (original GPKG + new GeoParquet) for 2-3 test countries, compare classified output row-for-row. Differences indicate a tag missing from the DuckDB WHERE clause.

---

## PostGIS as Live Combine Target

### Original approach (OOM on 32GB)

```r
points_combined <- rowbind(OSM_points_prep, OSM_multipolygons_prep, OVP_prep,
                           FSP_prep, ATP_prep, OCID_prep, ...)  # 100M rows in memory
qs::qsave(points_combined, out)
```

### Revised approach (no memory constraint)

Each source handler, after normalizing to the unified 16-column schema, appends directly to PostGIS:

```python
# Each source does this independently
df.to_postgis('gid_points_combined', engine, schema='silver', if_exists='append', index=False)
```

The "combine" node (Node 12) is a **health check**, not a data movement step:
- Verify expected source count (all sources have INSERTed)
- Verify no source has zero rows (detect silent failures)
- Run `ANALYZE silver.gid_points_combined`
- `REINDEX` if table was truncated and repopulated this run
- Log per-source row counts for auditability

Spatial indexes are created at table creation time (Phase 1), not after every pipeline run.

### Table Truncation Strategy

Since each source handler uses `if_exists='append'`, a second pipeline run would double the data without a truncation step.

**Decision: `TRUNCATE` at pipeline start.** Node 1 (`scope_countries`) truncates `silver.gid_points_combined` before any source handler begins INSERTing. This gives clean "full refresh" semantics:

```python
# In gid_load_country_filter handler, before returning:
with engine.connect() as conn:
    conn.execute(text("TRUNCATE silver.gid_points_combined"))
    conn.commit()
```

**Why TRUNCATE, not upsert:**
- `ON CONFLICT (id) DO UPDATE` would work but adds overhead on every INSERT for ~100M rows
- Upsert also can't handle source removals (a row deleted from upstream stays in our table)
- TRUNCATE + full repopulate is clean, simple, and matches Sebastian's original model (the R pipeline always rebuilds from scratch)

**Why in Node 1, not a separate node:**
- Node 1 runs before all source nodes. TRUNCATE here guarantees the table is empty before any INSERTs.
- No need for a separate "pre-clean" node — that's over-engineering the DAG.

The hex table (`silver.gid_hex_combined`) is handled similarly: the aggregation handler (Node 13) drops and recreates it each run via `CREATE TABLE ... AS SELECT`.

---

## H3 Aggregation via SQL

### Point aggregation (PostGIS + h3-pg)

```sql
-- Requires h3-pg extension
CREATE TABLE silver.gid_hex_points AS
SELECT
    h3_lat_lng_to_cell(ST_SetSRID(ST_MakePoint(lon, lat), 4326)::point, 6) AS h3_index,
    main_cat,
    count(*) AS n
FROM silver.gid_points_combined
GROUP BY 1, 2;

-- Pivot to wide format (generated dynamically from taxonomy config)
CREATE TABLE silver.gid_hex_points_wide AS
SELECT h3_index,
    count(*) FILTER (WHERE main_cat = 'health_essential') AS pt_health_essential,
    count(*) FILTER (WHERE main_cat = 'health_other') AS pt_health_other,
    count(*) FILTER (WHERE main_cat = 'education_essential') AS pt_education_essential,
    count(*) FILTER (WHERE main_cat = 'education_other') AS pt_education_other,
    count(*) FILTER (WHERE main_cat = 'power_plant_large') AS pt_power_plant_large,
    count(*) FILTER (WHERE main_cat = 'power_plant_small') AS pt_power_plant_small,
    -- ... (generated from taxonomy config, ~60 columns)
FROM silver.gid_points_combined
GROUP BY 1;
```

Zero Python/R memory used. PostGIS does the work.

### Line aggregation

This is the one area where Sebastian's R-based S2 approach may still be needed initially. His tiered spatial union + hex intersection logic is sophisticated. The PostGIS equivalent (`ST_Intersection` + `ST_Length` per hex cell) would work but needs benchmarking at global scale.

**Recommendation**: Keep line aggregation as a Python handler that reads line GeoParquets from the mount and writes results to PostGIS. This is the one piece that may not trivially convert to pure SQL. Flag for future optimization.

### H3 land grid

The land grid generation (filtering ocean-only hexes via landcover raster) remains a Python step using `h3` + `rasterio`. Output: Silver GeoParquet `h3_land_grid.parquet`.

---

## Handler Inventory (~14 handlers)

| # | Handler | Replaces (from Rev 1) | Description |
|---|---------|----------------------|-------------|
| 1 | `gid_load_country_filter` | same | Loads LMIC country list + bounding boxes from config. TRUNCATEs `silver.gid_points_combined` for clean repopulation. |
| 2 | `gid_fetch_overture_places` | `gid_fetch_overture_places` + `gid_fetch_overture_categories` + `gid_classify_overture` | DuckDB → S3, classify via crosswalk JSON, normalize, INSERT PostGIS |
| 3 | `gid_fetch_foursquare` | `gid_fetch_foursquare` + `gid_classify_foursquare` | DuckDB → S3, classify via crosswalk JSON, normalize, INSERT PostGIS |
| 4 | `gid_fetch_alltheplaces` | `gid_fetch_alltheplaces` + `gid_process_alltheplaces` | Download ZIP, parse GeoJSON, classify, normalize, INSERT PostGIS |
| 5 | `gid_fetch_opencellid` | `gid_fetch_opencellid` + `gid_process_opencellid` | Download CSV.GZ, MCC filter, normalize, INSERT PostGIS |
| 6 | `gid_fetch_portswatch` | `gid_fetch_portswatch` + `gid_process_portswatch` | Paginated REST fetch, normalize, INSERT PostGIS |
| 7 | `gid_load_config_source` | All 5 GEM handlers + `gid_load_solar_assets` + `gid_load_itu_nodes` + `gid_load_ozm_zones` | Config-driven: reads Excel/CSV/GeoJSON per YAML config, normalizes to unified schema, INSERT PostGIS. Supports sheet joins (GEM Steel two-sheet pattern). |
| 8 | `gid_fetch_ogim` | `gid_fetch_ogim` + `gid_process_ogim_points` + `gid_process_ogim_lines` | Zenodo fetch + multi-layer GPKG processing. Points → PostGIS, lines → Silver GeoParquet |
| 9 | `gid_osm_pbf_to_geoparquet` | OSM fetch + GPKG conversion | Downloads PBF per country → ogr2ogr -f Parquet on mount. No GPKG. |
| 10 | `gid_classify_osm` | `gid_classify_osm_r` | DuckDB reads filtered rows from GeoParquet → osmclass R subprocess → PostGIS |
| 11 | `gid_fetch_overture_transport` | 3 transport handlers (`_roads`, `_rail`, `_water`) | Single handler, parameterized by subtype list. Loops and writes one GeoParquet per subtype. |
| 12 | `gid_fetch_egm_grid` | `gid_fetch_egm_grid` + `gid_process_egm_grid` | Zenodo download + GPKG → GeoParquet (lines) |
| 13 | `gid_combine_to_postgis` | `gid_list_silver_point_sources` + `gid_combine_point_sources` + `gid_load_points_postgis` | **Health check only** — verifies all sources INSERTed, checks row counts, runs ANALYZE, REINDEX if truncated. No data movement. |
| 14 | `gid_aggregate_h3` | `gid_build_h3_land_grid` + `gid_aggregate_points_h3` + `gid_aggregate_lines_h3` + `gid_combine_hex_grids` + `gid_load_hex_postgis` + `gid_register_stac` | SQL-based point aggregation (h3-pg), line intersection from GeoParquets, outer join, write PostGIS table, STAC registration |

**Total: 14 handlers** (down from ~40 in Rev 1)

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

### GDAL Requirement

`ogr2ogr -f Parquet` requires GDAL 3.5+ with the Parquet driver compiled in. The existing Docker image uses `ghcr.io/osgeo/gdal` as a base, which includes this. Verify at build time with `ogr2ogr --formats | grep Parquet`.

---

## Database Schema

### New PostGIS Tables

```sql
-- Combined points from all sources (LIVE COMBINE TARGET)
-- Each source handler INSERTs directly to this table.
-- No in-memory rowbind.
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

-- Hex-aggregated infrastructure (FINAL OUTPUT)
-- Populated by SQL-based H3 aggregation, not in-memory pivot.
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

**Note**: The exact `pt_*` columns will be finalized after SPIKE-02/03 produce the complete taxonomy. The aggregation handler should generate the pivot SQL dynamically from the taxonomy config rather than hardcoding column names.

---

## Memory & Performance Constraints

### 8GB RAM Budget — Comfortable

The PBF→GeoParquet→DuckDB→PostGIS flow eliminates all memory bottlenecks. No operation loads more than one country's filtered features at a time.

| Operation | Memory Strategy | Peak RAM |
|-----------|----------------|----------|
| ogr2ogr PBF→Parquet | Streaming — GDAL never holds full PBF in memory | ~200-500 MB |
| DuckDB S3 Parquet queries | Streaming with predicate pushdown | ~1-2 GB |
| DuckDB local Parquet (OSM filter) | Predicate pushdown, only classification-relevant rows | ~2-4 GB (largest country) |
| OSM classification (R subprocess) | R process is isolated — OOM kills R, not Python worker | ~1-2 GB |
| PostGIS INSERT (per source) | Batch insert, memory freed between batches | ~500 MB |
| H3 aggregation | Server-side SQL — Python never loads rows | ~100 MB (query orchestration only) |
| Line aggregation | Only area that may need tiered processing | ~2-4 GB |
| Config source loading | Excel/CSV files are tiny (~50K rows total) | ~100 MB |

No DuckDB `memory_limit` workarounds needed.

### Estimated Data Volumes

| Dataset | Approximate Size | Post-LMIC-Filter |
|---------|-----------------|------------------|
| Overture Places (global) | ~72M rows | ~30-40M rows |
| Foursquare Places | ~50M rows | ~20-30M rows |
| OpenCellID | ~50M rows | ~20-30M rows |
| OSM (all LMICs) | ~100M features | ~5-10M (after classification filter) |
| Overture Transportation | ~200M segments | ~80-100M segments |
| GEM trackers (all 5) | ~50K rows total | ~30K rows |
| Final hex grid (H3 R6) | ~5M land hexes | ~3M LMIC hexes |

---

## Configuration Files

### Repo-Checked Config

```
config/gid/
├── lmic_countries.json           # Country list + ISO codes + bounding boxes
├── mcc_country_codes.json        # Mobile Country Codes for OpenCellID filtering
├── geofabrik_urls.json           # PBF download URLs per country (maintained, not scraped)
├── taxonomy/
│   ├── osmclass_categories.json  # Extracted from R osmclass package (SPIKE-02)
│   ├── osmclass_tag_keys.json    # All OSM tag keys in classification rules (SPIKE-02) — drives WHERE clause
│   ├── overture_to_osm.json      # Overture→OSM category mapping (SPIKE-03)
│   └── foursquare_to_osm.json    # Foursquare→OSM category mapping (SPIKE-03)
├── sources/
│   ├── gem_power.yaml            # GEM Power config for gid_load_config_source
│   ├── gem_cement.yaml           # GEM Cement config
│   ├── gem_iron.yaml             # GEM Iron config
│   ├── gem_chemicals.yaml        # GEM Chemicals config
│   ├── gem_steel.yaml            # GEM Steel config
│   ├── solar_assets.yaml         # TZ-SAM Solar config
│   ├── itu_nodes.yaml            # ITU Telecom config
│   ├── ozm_zones.yaml            # Open Zone Map config
│   ├── foursquare_s3_paths.json  # S3 paths for Foursquare data (maintained manually)
│   └── alltheplaces_url.json     # Download URL config (no HTML scraping)
└── r_scripts/
    └── classify_osm.R            # R script called via subprocess for osmclass
```

### Bronze Blob Layout

```
bronze/gid/
├── overture/
│   ├── places/                   # Fetched Overture places GeoParquet
│   ├── categories/               # Overture category taxonomy
│   └── transportation/
│       ├── road_segments.parquet
│       ├── rail_segments.parquet
│       └── water_segments.parquet
├── foursquare/
│   └── places/                   # Fetched Foursquare places GeoParquet
├── alltheplaces/
│   ├── output.zip                # Raw download
│   └── alltheplaces.parquet      # Processed
├── opencellid/
│   └── cell_towers.csv.gz
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
│   └── osm_classified.parquet
├── lines/
│   ├── overture_roads.parquet
│   ├── overture_rail.parquet
│   ├── overture_water.parquet
│   ├── egm_grid.parquet
│   └── ogim_pipelines.parquet
├── osm/
│   ├── {country}-points.parquet      # ogr2ogr output (mount working files)
│   ├── {country}-lines.parquet
│   └── {country}-multipolygons.parquet
├── hex/
│   ├── h3_land_grid.parquet
│   └── infrastructure_hex_h3r6.parquet  # FINAL OUTPUT (also in PostGIS)
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
- Verify config-driven handler loads each format (Excel, CSV, GeoJSON)

### Integration Tests (per DAG node)

- Submit each node handler with a small country subset (e.g., 2-3 small LMIC countries)
- Verify Bronze → Silver → PostGIS data flow
- Verify row counts are non-zero and reasonable

### PBF → GeoParquet Equivalence Test

Run both paths (original GPKG + new GeoParquet via ogr2ogr) for 2-3 test countries. Compare classified output row-for-row. Differences indicate a tag missing from the DuckDB WHERE clause.

### End-to-End Test

- Run `gid_pipeline.yaml` with a minimal country set
- Verify `silver.gid_points_combined` has rows from all sources
- Verify `silver.gid_hex_combined` has both point and line columns
- Verify PostGIS tables are queryable
- Verify STAC item is discoverable

### R Classification Validation

- Run `osmclass` via R subprocess on a known test dataset
- Compare output categories against expected values from the original R pipeline
- This is the critical fidelity check — the taxonomy must match

---

## What Stays Exactly The Same

To be explicit — the following are NOT changed by this design:

- Sebastian's `osmclass` classification rules (the R package)
- The Overture → OSM category crosswalk (46KB mapping file)
- The Foursquare → OSM category crosswalk
- The unified 16-column point schema
- The list of data sources and what's extracted from each
- The per-source normalization logic (ID generation, coordinate parsing, metadata packing)
- The priority ordering of classification categories
- The input data (same PBFs, same S3 parquets, same Excel files)

What changes is only the I/O layer: how data moves between steps, what format it's stored in between steps, and where the combine/aggregation happens (PostGIS instead of R memory).

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| GDAL Parquet driver not in Docker image | Blocks PBF→GeoParquet path | Verify `ogr2ogr --formats | grep Parquet` at build time. GDAL 3.5+ required. Existing osgeo/gdal base image includes it. |
| h3-pg extension not available in Azure PG Flexible Server | Blocks SQL-based aggregation | Check Azure PG extension list. Fallback: DuckDB h3 extension in Python handler. |
| OSM PBF download volume (~65GB) | Storage + time | Sequential download, delete PBF after conversion. Azure Files mount has sufficient capacity. |
| R subprocess adds image size | +300-400 MB | Acceptable for `osmclass` fidelity. Python port is documented exit strategy. |
| Overture S3 schema changes between releases | Breaks fetch handlers | Pin Overture release as workflow parameter. Handler validates expected columns. |
| Line aggregation is computationally expensive | Long-running task | Tiered geographic processing. Consider multiple workers. Janitor timeout must be generous (hours, not minutes). |
| Category taxonomy drift if upstream sources change | Misclassification | Taxonomy configs versioned in repo. Combine step validates and flags unknown categories. |
| GEM Excel sheet names change between releases | Load failure | Sheet names in YAML config, not hardcoded. Handler logs clear error on missing sheet. |
| DuckDB WHERE clause misses OSM tags | Rows lost vs original | Equivalence test catches this. WHERE clause derived from complete osmclass taxonomy (SPIKE-02 JSON). |

---

## Implementation Order

### Phase 0: Spikes (Resolve Before Implementation)
1. SPIKE-01: OSM-vs-Overture gap analysis
2. SPIKE-02: `osmclass` taxonomy extraction to JSON
3. SPIKE-03: Overture/Foursquare mapping extraction to JSON/YAML

### Phase 1: Foundation
1. **Resolve h3-pg availability** — Check if h3-pg extension is available in Azure PostgreSQL Flexible Server. If not, aggregation architecture changes from SQL queries to DuckDB h3 extension in Python handler. This must be answered before Phase 5 work begins.
2. Country filter config (`lmic_countries.json`)
3. Docker image update (r2u + R packages + Python deps + verify GDAL Parquet driver)
4. Unified schema validation utility
5. `gid_load_country_filter` handler (including TRUNCATE of `gid_points_combined`)
6. PostGIS table creation with indexes (`gid_points_combined`, `gid_hex_combined`)

### Phase 2: Config-Driven Sources (Validate Pattern)
1. Source config YAML files for all 8+ static sources
2. `gid_load_config_source` handler — validates the config-driven pattern
3. Test with GEM Power first (simplest Excel), then iterate through remaining configs

### Phase 3: DuckDB Sources (Core Pattern)
1. `gid_fetch_overture_places` — establishes DuckDB + S3 + PostGIS INSERT pattern
2. `gid_fetch_foursquare` — same pattern, different source
3. `gid_fetch_opencellid` — DuckDB reads CSV.GZ
4. `gid_fetch_overture_transport` — DuckDB, line data, parameterized subtypes

### Phase 4: Complex Sources
1. `gid_fetch_alltheplaces` — ZIP + GeoJSON processing
2. `gid_fetch_ogim` — GPKG with multiple layers (points + lines)
3. `gid_fetch_egm_grid` — GPKG, line data
4. `gid_osm_pbf_to_geoparquet` + `gid_classify_osm` — PBF→GeoParquet→DuckDB→osmclass→PostGIS

### Phase 5: Combine + Aggregate
1. `gid_combine_to_postgis` — validation + indexing
2. `gid_aggregate_h3` — SQL-based point aggregation + line aggregation + STAC registration
3. End-to-end test with minimal country set

### Phase 6: Wire DAG
1. `gid_pipeline.yaml` — single workflow YAML with all 13 nodes
2. Full pipeline test with 2-3 LMIC countries

---

## Open Questions

1. **Foursquare S3 access** — The original scrapes HTML docs for S3 paths. Need to determine if Foursquare provides a stable API or if we maintain S3 paths as config.
2. **AllThePlaces URL stability** — Is `data.alltheplaces.xyz/runs/latest/` a stable redirect? Or do we need to query their API?
3. **OpenCellID token management** — Token is in the original source code. Should we treat it as a secret in Azure Key Vault?
4. **GEM data refresh cadence** — GEM publishes quarterly. Should workflows auto-detect new versions, or is manual Bronze upload acceptable?
5. **Line aggregation parallelism** — The tiered spatial processing is single-threaded in the original. Should we fan-out by geographic tile for parallel processing?
6. ~~**PostGIS table versioning**~~ — **Resolved**: TRUNCATE + repopulate (full refresh) each run. No versioned table names. See "Table Truncation Strategy" section.
7. **GDAL Parquet driver** — Does our Docker image's GDAL version support `ogr2ogr -f Parquet`? Requires GDAL 3.5+. Verify at build time.

**Resolved (moved to Phase 1)**: h3-pg extension availability in Azure PostgreSQL Flexible Server. Must be answered before aggregation implementation.
