# Fathom Flood Hazard Data ETL Pipeline

**Date**: 25 NOV 2025
**Status**: Architecture & Discovery Phase

---

## Overview

This document records our work on building an ETL pipeline for **Fathom Global Flood Hazard Maps v3 (2023)** data. The data represents flood depth rasters for multiple flood types, climate scenarios, return periods, and projection years.

**Source**: Fathom (SSBN) Global Flood Hazard Maps
**Dataset**: Côte d'Ivoire (CI) - Sample/pilot dataset (0.14% of global)
**Location**: `bronze-fathom` container in `rmhazuregeo` storage account

### Global Dataset Scale

| Metric | Côte d'Ivoire (Sample) | Global (Estimated) |
|--------|------------------------|-------------------|
| **Files** | 15,392 | ~11 million |
| **Storage** | ~500 MB | ~8 TB |
| **1° Tiles** | 44 | ~17,000-25,000 |

---

## Data Discovery Summary

### Container Structure

```
bronze-fathom/
├── CI_Côte_d'Ivoire_file_list.csv     # Index file (15,392 file paths)
├── COASTAL_DEFENDED/                   # Flood type 1
├── COASTAL_UNDEFENDED/                 # Flood type 2
├── FLUVIAL_DEFENDED/                   # Flood type 3
├── FLUVIAL_UNDEFENDED/                 # Flood type 4
└── PLUVIAL_DEFENDED/                   # Flood type 5
```

### File Counts

| Metric | Value |
|--------|-------|
| **Total Files** | 15,392 |
| **Flood Types** | 5 |
| **Years** | 4 (2020, 2030, 2050, 2080) |
| **Return Periods** | 8 (1in5, 1in10, 1in20, 1in50, 1in100, 1in200, 1in500, 1in1000) |
| **Climate Scenarios** | 4 (SSP1_2.6, SSP2_4.5, SSP3_7.0, SSP5_8.5) |
| **Unique Tile Grid Cells** | 44 (1-degree tiles) |
| **Avg File Size** | ~50-100 KB |

---

## Hierarchical File Pattern

### Folder Structure

```
{FLOOD_TYPE}/
└── {YEAR}/
    └── {RETURN_PERIOD or SSP_SCENARIO}/
        └── {filename}.tif
```

### Dimension Values

#### Flood Types (5)
| Code | Description |
|------|-------------|
| `COASTAL_DEFENDED` | Coastal flooding with flood defenses |
| `COASTAL_UNDEFENDED` | Coastal flooding without defenses |
| `FLUVIAL_DEFENDED` | River flooding with defenses |
| `FLUVIAL_UNDEFENDED` | River flooding without defenses |
| `PLUVIAL_DEFENDED` | Surface water/rainfall flooding with defenses |

#### Years (4)
- `2020` - Baseline/current conditions
- `2030` - Near-term projection
- `2050` - Mid-century projection
- `2080` - End-century projection

#### Return Periods (8)
Annual Exceedance Probability (AEP):
| Return Period | AEP | Description |
|---------------|-----|-------------|
| `1in5` | 20% | Very frequent |
| `1in10` | 10% | Frequent |
| `1in20` | 5% | Common |
| `1in50` | 2% | Moderate |
| `1in100` | 1% | Infrequent (standard design flood) |
| `1in200` | 0.5% | Rare |
| `1in500` | 0.2% | Very rare |
| `1in1000` | 0.1% | Extreme |

#### Climate Scenarios (4) - For Future Years
| Scenario | Description |
|----------|-------------|
| `SSP1_2.6` | Sustainability pathway, low emissions |
| `SSP2_4.5` | Middle of the road |
| `SSP3_7.0` | Regional rivalry, high emissions |
| `SSP5_8.5` | Fossil-fueled development, very high emissions |

---

## Filename Patterns

### Baseline Year (2020)
```
{RETURN_PERIOD}-{FLOOD_TYPE}-{YEAR}_{TILE}.tif

Examples:
  1in10-COASTAL-DEFENDED-2020_n04w006.tif
  1in100-FLUVIAL-UNDEFENDED-2020_n07w005.tif
  1in1000-PLUVIAL-DEFENDED-2020_n09w008.tif
```

### Future Years (2030, 2050, 2080)
```
{RETURN_PERIOD}-{FLOOD_TYPE}-{YEAR}-{SSP_SCENARIO}_{TILE}.tif

Examples:
  1in10-COASTAL-DEFENDED-2030-SSP1_2.6_n04w006.tif
  1in100-FLUVIAL-UNDEFENDED-2050-SSP3_7.0_n07w005.tif
  1in1000-PLUVIAL-DEFENDED-2080-SSP5_8.5_n09w008.tif
```

### Tile Coordinate System
- Format: `{n|s}{lat}{e|w}{lon}` (1-degree grid cells)
- Example: `n04w006` = North 4°, West 6° (covers 4°N-5°N, 6°W-7°W)

### Tile Coverage (Côte d'Ivoire)
```
Latitude:  4°N to 10°N (7 rows)
Longitude: 3°W to 9°W (7 cols)
Total: 44 tiles (not all grid cells have data - coastal areas only)
```

---

## Data Structure by Flood Type

### Coastal Flooding (DEFENDED & UNDEFENDED)
- **2020**: 8 return periods × 8 tiles = 64 files each
- **Future**: 4 SSP × 8 return periods × 8 tiles = 256 files each per year

### Fluvial & Pluvial Flooding (DEFENDED & UNDEFENDED)
- **2020**: 8 return periods × 44 tiles = 352 files each
- **Future**: 4 SSP × 8 return periods × 44 tiles = 1,408 files each per year

---

## Full Hierarchy Breakdown

```
COASTAL_DEFENDED/
  2020/
    1in5/    (8 files)
    1in10/   (8 files)
    1in20/   (8 files)
    1in50/   (8 files)
    1in100/  (8 files)
    1in200/  (8 files)
    1in500/  (8 files)
    1in1000/ (8 files)
  2030/
    SSP1_2.6/ (64 files: 8 return periods × 8 tiles)
    SSP2_4.5/ (64 files)
    SSP3_7.0/ (64 files)
    SSP5_8.5/ (64 files)
  2050/
    [same as 2030]
  2080/
    [same as 2030]

FLUVIAL_DEFENDED/
  2020/
    1in5/    (44 files)
    1in10/   (44 files)
    ...      (44 files each)
  2030/
    SSP1_2.6/ (352 files: 8 return periods × 44 tiles)
    SSP2_4.5/ (352 files)
    SSP3_7.0/ (352 files)
    SSP5_8.5/ (352 files)
  [2050, 2080 same pattern]
```

---

## ETL Pipeline Design Considerations

### STAC Catalog Structure Options

#### Option A: One Collection Per Combination
```
fathom-flood-ci-coastal-defended-2020-1in100
fathom-flood-ci-fluvial-undefended-2050-ssp245-1in100
```
- **Pros**: Simple queries, clear separation
- **Cons**: 100+ collections, management overhead

#### Option B: Hierarchical Collections with Properties
```
fathom-flood-ci/
├── coastal-defended/
│   └── items with properties: {year, return_period, ssp_scenario, tile}
├── coastal-undefended/
├── fluvial-defended/
├── fluvial-undefended/
└── pluvial-defended/
```
- **Pros**: Manageable collections (5), filter by properties
- **Cons**: Requires good property indexing

#### Option C: Single Collection with Rich Metadata
```
fathom-flood-ci/
└── items with properties: {flood_type, defense_status, year, return_period, ssp_scenario, tile}
```
- **Pros**: Simplest structure, maximum flexibility
- **Cons**: All filtering via properties

### Recommended: Option B (Hierarchical by Flood Type)

**Rationale**:
1. Flood type is the primary analytical dimension
2. 5 collections is manageable
3. Properties handle temporal/scenario filtering
4. Matches how users typically query flood data

---

## Pipeline Stages (Draft)

### Stage 1: Validate & Inventory
- Read CSV file list
- Validate files exist in blob storage
- Parse metadata from filenames
- Create inventory table in PostgreSQL

### Stage 2: Generate COGs (if needed)
- Check if source TIFs are already COG-optimized
- Convert to COGs if necessary
- Upload to silver storage tier

### Stage 3: Create STAC Items
- Generate STAC item for each tile
- Include all metadata as properties
- Calculate bbox from tile coordinates

### Stage 4: Register in pgstac
- Create STAC collections (5 total)
- Insert STAC items
- Build spatial indices

### Stage 5: Create MosaicJSON (optional)
- For visualization, create mosaic definitions
- Group by flood_type + year + return_period + scenario

---

## Raster Technical Specifications (25 NOV 2025)

### Format Analysis

| Property | Value |
|----------|-------|
| **Format** | GeoTIFF with COG layout |
| **Already COG?** | YES - no conversion needed |
| **Compression** | DEFLATE |
| **Internal Tiling** | 256x256 pixels |
| **CRS** | EPSG:4326 (WGS84) |
| **Pixel Size** | 0.000277778° (~1 arc-second, ~30m at equator) |
| **Data Type** | Int16 (signed 16-bit integer) |
| **Tile Dimensions** | 3600 x 3600 pixels (1° x 1°) |

### Value Encoding

| Value | Meaning |
|-------|---------|
| **-32768** | NoData (outside model domain, e.g., ocean) |
| **-32767** | Sentinel value (used in some tiles for no-data areas) |
| **0** | Dry land / no flooding |
| **1-32767** | Flood depth in **CENTIMETERS** |

**Note**: Values are in CENTIMETERS, not meters. Max value ~10m (1000cm).

### Compression Efficiency

The data is extremely sparse - most pixels are dry land or ocean:

| Flood Type | Data Density | Compression Ratio | File Size |
|------------|--------------|-------------------|-----------|
| **Coastal** | 0.04% flooded | 237x | ~100 KB |
| **Fluvial** | 2.09% flooded | 52x | ~500 KB |
| **Pluvial** | 16.73% flooded | 8x | ~3.3 MB |

Raw uncompressed size per tile: 24.7 MB (3600×3600×2 bytes)

### Flood Depth Distribution (Sample Analysis)

**Coastal Flooding** (1in100, 2020):
- Min: 5 cm, Max: 142 cm
- Mean: 34 cm, Median: 29 cm
- 86% of flooded pixels: 10-100 cm depth

**Fluvial Flooding** (1in100, 2020):
- Min: 5 cm, Max: 757 cm (~7.5m)
- Mean: 149 cm, Median: 130 cm
- 62% of flooded pixels: 50-200 cm depth

**Pluvial Flooding** (1in100, 2020):
- Min: 5 cm, Max: 1000 cm (10m, likely capped)
- Mean: 50 cm, Median: 30 cm
- 66% of flooded pixels: 10-100 cm depth

---

## ETL Strategy Revision

### Design Constraints

| Constraint | Priority | Notes |
|------------|----------|-------|
| **Storage cost** | NOT a concern | Virtually unlimited Azure budget |
| **Compute cost** | HIGH priority | Web apps and database are expensive |
| **File count** | HIGH priority | 11M files = 11M pgstac records = unmanageable |
| **MosaicJSON** | NOT viable | Doesn't work with dynamic storage tokens |

**Goal**: Physically consolidate 11M small files into fewer large files.

### Spatial Consolidation Strategy (26 NOV 2025)

| Approach | Global Files | Avg File Size | CI Files | Notes |
|----------|--------------|---------------|----------|-------|
| **1×1 (current)** | 11,000,000 | ~50 KB | 15,392 | Unmanageable |
| **5×5 grid** | 52,000 | ~165 MB | 390 | Consistent tiles globally |
| **Country-based** | 13,000 | ~200-500 MB | 65 | Natural boundaries, fewer files |

**Decision**: **Country-based consolidation** for CI pilot
- CI spans 7°×7° (44 source tiles), single merged extent per layer
- 65 output files vs 390 files (if using 5×5 grid)
- File sizes ~200-350 MB each (well under 1GB target)
- Natural political boundaries simplify downstream access patterns

**Global Strategy**: Evaluate after pilot - may use 5×5 grid for large countries (Russia, Canada, Brazil) to keep files under 1GB, while using country extent for smaller nations.

### Consolidation Strategy: Multi-Band Regional COGs

**Approach**: Merge tiles spatially + stack return periods as bands

| Metric | Before | After | Reduction |
|--------|--------|-------|-----------|
| Files (CI) | 15,392 | **65** | 237x |
| Files (Global) | ~11M | **~13,000** | 850x |
| STAC Items (CI) | 15,392 | **65** | 237x |
| STAC Items (Global) | ~11M | **~13,000** | 850x |

### Output File Structure

Each output file:
- **Spatial merge**: All tiles for a region combined into single raster
- **Band stack**: 8 return periods as bands (1in5 through 1in1000)
- **Format**: Cloud Optimized GeoTIFF with DEFLATE compression

**Band mapping**:
| Band | Return Period | Description |
|------|---------------|-------------|
| 1 | 1in5 | 20% annual probability |
| 2 | 1in10 | 10% annual probability |
| 3 | 1in20 | 5% annual probability |
| 4 | 1in50 | 2% annual probability |
| 5 | 1in100 | 1% annual probability (design flood) |
| 6 | 1in200 | 0.5% annual probability |
| 7 | 1in500 | 0.2% annual probability |
| 8 | 1in1000 | 0.1% annual probability |

### Output File Naming

```
fathom_{region}_{flood_type}_{year}[_{ssp}].tif

Examples:
  fathom_ci_coastal-defended_2020.tif           # 8 bands, baseline
  fathom_ci_fluvial-defended_2050_ssp245.tif    # 8 bands, future scenario
```

### File Count Breakdown

**Per region (e.g., Côte d'Ivoire)**:
- 2020 baseline: 5 flood types = **5 files**
- Future years: 5 flood types × 3 years × 4 SSP = **60 files**
- **Total: 65 files per region**

**Global**:
- ~200 countries × 65 files = **~13,000 files**
- Much more manageable than 11 million!

### Côte d'Ivoire Pilot: 65 Output Files

```
fathom_ci_coastal-defended_2020.tif
fathom_ci_coastal-undefended_2020.tif
fathom_ci_fluvial-defended_2020.tif
fathom_ci_fluvial-undefended_2020.tif
fathom_ci_pluvial-defended_2020.tif
fathom_ci_coastal-defended_2030_ssp126.tif
fathom_ci_coastal-defended_2030_ssp245.tif
... (60 more future scenario files)
```

### ETL Pipeline Stages

```
Stage 1: INVENTORY
   Parse CSV → Group 15,392 files into 65 output targets
   Each group: same flood_type + year + scenario, all return periods

Stage 2: MERGE (parallelizable - 65 independent tasks)
   For each output file:
   a) Build VRT for spatial merge of tiles (per return period)
   b) Stack 8 VRTs as bands
   c) Convert to COG with DEFLATE compression
   Output: ~200 MB per file, ~13 GB total for CI

Stage 3: UPLOAD TO SILVER
   Upload 65 COGs to silver-cogs container

Stage 4: CREATE STAC ITEMS
   Generate 65 STAC items with:
   - Properties: flood_type, defense_status, year, ssp_scenario
   - Band descriptions for return periods
   - Asset pointing to COG

Stage 5: REGISTER IN PGSTAC
   Create collection: fathom-flood-ci
   Insert 65 items
```

### Storage Architecture

```
bronze-fathom/                    # Source data (read-only)
├── COASTAL_DEFENDED/
│   └── 2020/1in100/*.tif        # Original 15,392 tiles
└── ...

silver-cogs/                      # Consolidated output
└── fathom/
    └── ci/                       # Côte d'Ivoire (65 files, ~13 GB)
        ├── fathom_ci_coastal-defended_2020.tif
        ├── fathom_ci_fluvial-defended_2050_ssp245.tif
        └── ...

pgstac/                           # Catalog
└── collection: fathom-flood-ci
    └── 65 items
```

### STAC Item Structure

```json
{
  "type": "Feature",
  "id": "fathom-ci-fluvial-defended-2050-ssp245",
  "collection": "fathom-flood-ci",
  "properties": {
    "flood_type": "fluvial",
    "defense_status": "defended",
    "year": 2050,
    "ssp_scenario": "SSP2-4.5",
    "datetime": "2050-01-01T00:00:00Z",
    "fathom:depth_unit": "cm",
    "fathom:source_tiles": 44,
    "eo:bands": [
      {"name": "1in5", "description": "20% annual exceedance probability"},
      {"name": "1in10", "description": "10% annual exceedance probability"},
      {"name": "1in20", "description": "5% annual exceedance probability"},
      {"name": "1in50", "description": "2% annual exceedance probability"},
      {"name": "1in100", "description": "1% annual exceedance probability"},
      {"name": "1in200", "description": "0.5% annual exceedance probability"},
      {"name": "1in500", "description": "0.2% annual exceedance probability"},
      {"name": "1in1000", "description": "0.1% annual exceedance probability"}
    ]
  },
  "assets": {
    "data": {
      "href": "https://rmhazuregeo.blob.../silver-cogs/fathom/ci/fathom_ci_fluvial-defended_2050_ssp245.tif",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "roles": ["data"]
    }
  },
  "bbox": [-8.6, 4.3, -2.5, 10.7],
  "geometry": { "type": "Polygon", "coordinates": [...] }
}
```

### Query Examples

**"Show me 1in100 fluvial flooding in 2050 under SSP2-4.5"**
→ Find item `fathom-ci-fluvial-defended-2050-ssp245`, read band 5

**"Compare 1in100 vs 1in1000 for same scenario"**
→ Same item, read bands 5 and 8

**"All flooding scenarios for 2050"**
→ Query items where year=2050 (returns 20 items: 5 flood types × 4 SSP)

---

## Implementation Status (26 NOV 2025)

### Completed ✅

1. [x] Sample TIF files and inspect with gdalinfo
2. [x] Verify COG format and compression
3. [x] Document value encoding and ranges
4. [x] Design consolidation strategy (multi-band COGs, return periods as bands)
5. [x] Decide spatial consolidation approach (country-based for CI pilot)
6. [x] Create JobBaseMixin job class: `process_fathom`
7. [x] Implement task handlers (inventory, merge_stack, stac_register)
8. [x] Register job and handlers in `__init__.py` files
9. [x] Test rasterio merge/stack workflow locally

### Files Created

| File | Purpose | Lines |
|------|---------|-------|
| `jobs/process_fathom.py` | Job definition using JobBaseMixin | ~350 |
| `services/fathom_etl.py` | Task handlers (inventory, merge, STAC) | ~650 |

### Pending

10. [ ] Deploy to Azure Functions
11. [ ] Test full pipeline with CI subset
12. [ ] Scale to global dataset

---

## Usage

### Submit Job (CI Pilot)

```bash
# Dry run - inventory only, no file processing
curl -X POST https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/process_fathom \
  -H "Content-Type: application/json" \
  -d '{"region_code": "CI", "dry_run": true}'

# Full processing (65 output files)
curl -X POST https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/process_fathom \
  -H "Content-Type: application/json" \
  -d '{"region_code": "CI"}'

# Process only specific flood types
curl -X POST https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/process_fathom \
  -H "Content-Type: application/json" \
  -d '{"region_code": "CI", "flood_types": ["FLUVIAL_DEFENDED"]}'
```

### Check Job Status

```bash
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}
```

### Query STAC Catalog

```bash
# List collections
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/stac/collections

# Get Fathom CI collection
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/stac/collections/fathom-flood-ci

# Search items by flood type
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/stac/search?collections=fathom-flood-ci&filter=fathom:flood_type='fluvial'"
```

---

## Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        ProcessFathomWorkflow                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Stage 1: INVENTORY (single task)                                       │
│  ├── Parse CSV file list                                                │
│  ├── Group 15,392 files into 65 merge targets                          │
│  └── Output: merge_groups[] for Stage 2                                 │
│                           ↓                                              │
│  Stage 2: MERGE_STACK (65 parallel tasks)                               │
│  ├── Download tiles for each return period                              │
│  ├── Spatial merge using rasterio.merge()                               │
│  ├── Stack 8 return periods as bands                                    │
│  ├── Write COG with overviews                                           │
│  └── Upload to silver-cogs/fathom/ci/                                   │
│                           ↓                                              │
│  Stage 3: STAC_REGISTER (fan-in task)                                   │
│  ├── Create fathom-flood-ci collection                                  │
│  ├── Create 65 STAC items with band metadata                            │
│  └── Register in pgstac                                                  │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## References

- [Fathom Global Flood Maps](https://www.fathom.global/)
- [STAC Specification](https://stacspec.org/)
- [COG Specification](https://www.cogeo.org/)
- [SSP Scenarios (IPCC)](https://www.ipcc.ch/report/ar6/wg1/)

---

**File**: `fathom/FATHOM.md`
**Last Updated**: 26 NOV 2025