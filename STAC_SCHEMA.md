# STAC Item & Collection Schema

**Last Updated**: 26 MAR 2026
**Audience**: Data owners and platform consumers (DDH integration team)
**Version**: v0.10.6 — Consolidated STAC schema

---

## What Is STAC?

STAC (SpatioTemporal Asset Catalog) is an open specification for describing geospatial data so it can be searched, discovered, and accessed programmatically. It provides a standardized metadata envelope around every published dataset.

The platform uses STAC as the **discovery and access layer**. Once data is processed and approved, it appears in the STAC catalog. Consumers query the catalog to find data, then access it through TiTiler for visualization.

**Key principle**: STAC items in this catalog are a **materialized view** of internal metadata. The catalog can be rebuilt from the internal database at any time. It contains only consumer-facing fields — no internal plumbing.

---

## Two Levels: Collections and Items

```
STAC Catalog
  |
  +-- Collection: "jakarta-flood-depth"
  |     |
  |     +-- Item: "jakarta-flood-depth-v1"  (a single COG raster)
  |     +-- Item: "jakarta-flood-depth-v2"  (updated version)
  |
  +-- Collection: "global-spei12-ssp370"
  |     |
  |     +-- Item: "spei12-ssp370-median"    (a Zarr store)
  |
  +-- Collection: "nairobi-dem-tiled"
        |
        +-- Item: "nairobi-dem-R0C0"        (tile 1 of N)
        +-- Item: "nairobi-dem-R0C1"        (tile 2 of N)
        +-- Item: "nairobi-dem-R1C0"        (tile 3 of N)
        ...
```

A **Collection** groups related items. An **Item** represents one data resource (a file, a tile, a Zarr store) with its metadata and access URLs.

---

## STAC Item Structure

Every item in the catalog follows this structure. Fields marked **(always)** are guaranteed present. Fields marked **(when available)** depend on the metadata extractable from the source data.

### 1. Identity

| Field | Example | Notes |
|-------|---------|-------|
| `id` | `"jakarta-flood-depth-v1"` | Unique within the collection. Includes version for approved items. |
| `collection` | `"jakarta-flood-depth"` | Parent collection identifier. |
| `stac_version` | `"1.0.0"` | Always 1.0.0. |

### 2. Spatial Extent (always)

Every item includes a bounding box and geometry in WGS84 (EPSG:4326):

```json
{
  "bbox": [-77.028, 38.908, -77.013, 38.932],
  "geometry": {
    "type": "Polygon",
    "coordinates": [[[-77.028, 38.908], [-77.013, 38.908], [-77.013, 38.932], [-77.028, 38.932], [-77.028, 38.908]]]
  }
}
```

This enables spatial search — finding all items that intersect a given region.

### 3. Temporal (always)

| Field | Value | Notes |
|-------|-------|-------|
| `datetime` | `"2024-06-15T00:00:00Z"` | Acquisition or reference date, when known. |
| `datetime` | `"0001-01-01T00:00:00Z"` | Sentinel value indicating unknown date. |
| `start_datetime` / `end_datetime` | Date range | For time-series data (e.g., Zarr stores covering 2020-2024). |

Many raster datasets lack embedded temporal information. Unknown dates use `0001-01-01` as an unambiguous placeholder that can be replaced with a valid date when the information is available.

### 4. Assets — Data Access (always)

Assets are the data resources. Every item has at least one asset.

**Raster data (COG)**:
```json
{
  "assets": {
    "data": {
      "href": "/vsiaz/silver-cogs/jakarta/flood_depth_v1.tif",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "roles": ["data"],
      "raster:bands": [
        {
          "data_type": "float32",
          "statistics": {"minimum": 0.0, "maximum": 12.5, "mean": 2.3}
        }
      ]
    },
    "thumbnail": {
      "href": "https://titiler.../cog/preview.png?url=...",
      "type": "image/png",
      "roles": ["thumbnail"]
    }
  }
}
```

**Zarr data**:
```json
{
  "assets": {
    "zarr-store": {
      "href": "abfs://silver-zarr/spei12-ssp370/store.zarr",
      "type": "application/vnd+zarr",
      "roles": ["data"]
    }
  }
}
```

### 5. Visualization — TiTiler Links (always for raster)

Raster items include links to TiTiler for live map rendering:

```json
{
  "links": [
    {
      "rel": "tiles",
      "href": "https://titiler.../cog/WebMercatorQuad/tilejson.json?url=...",
      "type": "application/json",
      "title": "TileJSON"
    }
  ]
}
```

The **TileJSON** URL is the primary access mechanism. Any web map client (Leaflet, MapLibre, OpenLayers) can consume this URL to render the data as map tiles. No direct file access is required.

For tiled collections (many tiles composited into one view), a **mosaic** search is registered, providing a single TileJSON URL that renders all tiles as one seamless layer.

### 6. Visualization Hints — Renders Extension (when available)

The `renders` property provides TiTiler with automatic visualization configuration:

```json
{
  "renders": {
    "default": {
      "title": "Default visualization",
      "assets": ["data"],
      "rescale": [[0, 8848]],
      "colormap_name": "terrain"
    },
    "grayscale": {
      "title": "Grayscale",
      "assets": ["data"],
      "rescale": [[0, 8848]]
    }
  }
}
```

| Raster Type | Default Colormap | Visual |
|-------------|-----------------|--------|
| DEM / elevation | `terrain` | Green lowlands, brown mountains, white peaks |
| Flood depth | `blues` | Light blue (shallow) to dark blue (deep) |
| Flood probability | `reds` | Light red (low) to dark red (high) |
| Vegetation index | `rdylgn` | Red (bare) to green (vegetated) |
| Population density | `ylorrd` | Yellow (sparse) to red (dense) |
| RGB imagery | Natural color | No colormap needed |

TiTiler reads these automatically via `?render_id=default` on any TileJSON URL.

### 7. Projection (when available)

```json
{
  "proj:epsg": 4326,
  "proj:transform": [0.000003, 0.0, -77.028, 0.0, -0.000003, 38.932, 0.0, 0.0, 1.0]
}
```

The coordinate reference system and affine transform. Most data is reprojected to EPSG:4326 (WGS84) during processing. The original CRS is preserved for consumers that require it.

### 8. Platform References — DDH Linkage (when provided)

These fields link the STAC item back to the DDH metadata hierarchy:

```json
{
  "ddh:dataset_id": "jakarta-floods",
  "ddh:resource_id": "flood-depth-2024",
  "ddh:version_id": "v1.0",
  "ddh:access_level": "public"
}
```

| Field | Purpose |
|-------|---------|
| `ddh:dataset_id` | Corresponds to the DDH dataset identifier. |
| `ddh:resource_id` | Corresponds to the DDH resource within the dataset. |
| `ddh:version_id` | Version identifier assigned at approval. |
| `ddh:access_level` | `"public"` or `"ouo"` (Official Use Only). Assigned at approval. |

These fields are present only on **approved** items.

### 9. Geographic Attribution (when available)

```json
{
  "geo:iso3": ["IDN"],
  "geo:primary_iso3": "IDN",
  "geo:countries": ["Indonesia"]
}
```

Country-level attribution derived from the item's bounding box. Enables attribute-based search by country or region.

### 10. Zarr-Specific Properties (Zarr items only)

```json
{
  "zarr:variables": ["temperature", "precipitation", "wind_speed"],
  "zarr:dimensions": {"time": 365, "lat": 720, "lon": 1440}
}
```

For Zarr stores, these describe the data variables and array dimensions.

---

## STAC Collection Structure

Collections describe the group, not individual items:

```json
{
  "type": "Collection",
  "id": "jakarta-flood-depth",
  "stac_version": "1.0.0",
  "description": "Flood depth analysis for Jakarta metropolitan area",
  "license": "proprietary",
  "extent": {
    "spatial": {"bbox": [[-77.028, 38.908, -77.013, 38.932]]},
    "temporal": {"interval": [["2024-01-01T00:00:00Z", "2024-12-31T00:00:00Z"]]}
  },
  "geo:iso3": ["IDN"],
  "geo:primary_iso3": "IDN",
  "geo:countries": ["Indonesia"]
}
```

The spatial and temporal extent is the **union** of all items in the collection, recomputed when items are added or removed.

---

## STAC Extensions

Extensions add standardized fields beyond the core STAC specification:

| Extension | Fields | Purpose |
|-----------|--------|---------|
| [Projection](https://github.com/stac-extensions/projection) | `proj:epsg`, `proj:wkt2`, `proj:transform` | Coordinate reference system |
| [Raster](https://github.com/stac-extensions/raster) | `raster:bands` (on assets) | Band statistics, data types, nodata values |
| [Render](https://github.com/stac-extensions/render) | `renders` | Visualization configuration for TiTiler |

The `stac_extensions` array on each item declares which extensions are active:

```json
{
  "stac_extensions": [
    "https://stac-extensions.github.io/projection/v1.0.0/schema.json",
    "https://stac-extensions.github.io/raster/v1.1.0/schema.json",
    "https://stac-extensions.github.io/render/v2.0.0/schema.json"
  ]
}
```

---

## Querying the Catalog

### List all collections
```bash
GET /api/stac/collections
```

### List items in a collection
```bash
GET /api/stac/collections/{collection_id}/items
```

### Search by bounding box
```bash
POST /api/stac/search
{
  "bbox": [106.7, -6.3, 106.9, -6.1],
  "collections": ["jakarta-flood-depth"]
}
```

### Search by date range
```bash
POST /api/stac/search
{
  "datetime": "2024-01-01/2024-12-31",
  "collections": ["jakarta-flood-depth"]
}
```

---

## Lifecycle: How Data Reaches the Catalog

```
1. UPLOAD      Data owner uploads file to Bronze storage
                  |
2. PROCESS     ETL pipeline creates COG/Zarr, extracts metadata
                  |
3. CACHE       STAC item JSON cached in internal database
               (not yet visible in catalog)
                  |
4. APPROVE     Reviewer approves the release
               Platform refs (ddh:*) and access level stamped
                  |
5. MATERIALIZE Item written to pgSTAC catalog
               TiTiler URLs injected
               Collection extent updated
                  |
6. DISCOVER    Item visible via STAC API
               TiTiler serves map tiles
```

Items are **not visible** in the STAC catalog until approved. Before approval, metadata exists only in the internal database.

---

## Complete Examples

### Example: Raster COG Item (Single File)

A 3-band RGB aerial image of Washington DC, approved for public access:

```json
{
  "type": "Feature",
  "stac_version": "1.0.0",
  "stac_extensions": [
    "https://stac-extensions.github.io/projection/v1.0.0/schema.json",
    "https://stac-extensions.github.io/raster/v1.1.0/schema.json",
    "https://stac-extensions.github.io/render/v2.0.0/schema.json"
  ],
  "id": "dc-aerial-imagery-v1",
  "collection": "dc-aerial-imagery",
  "bbox": [-77.028, 38.908, -77.013, 38.932],
  "geometry": {
    "type": "Polygon",
    "coordinates": [[
      [-77.028, 38.908], [-77.013, 38.908],
      [-77.013, 38.932], [-77.028, 38.932],
      [-77.028, 38.908]
    ]]
  },
  "properties": {
    "datetime": "2024-06-15T00:00:00Z",
    "title": "dc-aerial-imagery-v1",
    "proj:epsg": 4326,
    "proj:transform": [3.078e-06, 0.0, -77.028, 0.0, -3.078e-06, 38.932, 0.0, 0.0, 1.0],
    "renders": {
      "default": {
        "title": "Natural color",
        "assets": ["data"]
      }
    },
    "ddh:dataset_id": "dc-aerial",
    "ddh:resource_id": "imagery-2024",
    "ddh:version_id": "v1",
    "ddh:access_level": "public",
    "ddh:approved_by": "reviewer@worldbank.org",
    "ddh:approved_at": "2026-03-25T22:24:30Z",
    "geo:iso3": ["USA"],
    "geo:primary_iso3": "USA",
    "geo:countries": ["United States"]
  },
  "assets": {
    "data": {
      "href": "/vsiaz/silver-cogs/dc-aerial/imagery-2024/1/imagery_cog.tif",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "roles": ["data"],
      "raster:bands": [
        {
          "data_type": "uint8",
          "statistics": {"minimum": 17, "maximum": 254, "mean": 96.15},
          "common_name": "red"
        },
        {
          "data_type": "uint8",
          "statistics": {"minimum": 36, "maximum": 255, "mean": 105.47},
          "common_name": "green"
        },
        {
          "data_type": "uint8",
          "statistics": {"minimum": 35, "maximum": 254, "mean": 102.94},
          "common_name": "blue"
        }
      ]
    },
    "thumbnail": {
      "href": "https://rmhtitiler-.../cog/preview.png?url=...",
      "type": "image/png",
      "roles": ["thumbnail"]
    }
  },
  "links": [
    {
      "rel": "tiles",
      "href": "https://rmhtitiler-.../cog/WebMercatorQuad/tilejson.json?url=...",
      "type": "application/json",
      "title": "TileJSON"
    }
  ]
}
```

**Consumer usage**:
1. `assets.data.raster:bands` — band structure (3-band RGB, uint8)
2. `links[rel=tiles].href` — map tile rendering endpoint
3. `assets.thumbnail.href` — quick preview image
4. `properties.renders.default` — confirms TiTiler auto-visualization as natural color
5. `ddh:dataset_id` / `ddh:resource_id` — links back to DDH metadata hierarchy

### Example: Zarr Store Item (Climate Time-Series)

SPEI-12 drought index projections stored as a Zarr array:

```json
{
  "type": "Feature",
  "stac_version": "1.0.0",
  "stac_extensions": [
    "https://stac-extensions.github.io/processing/v1.2.0/schema.json"
  ],
  "id": "spei12-ssp370-median-2040-2059",
  "collection": "global-spei12-projections",
  "bbox": [-180.0, -90.0, 180.0, 90.0],
  "geometry": {
    "type": "Polygon",
    "coordinates": [[
      [-180, -90], [180, -90], [180, 90], [-180, 90], [-180, -90]
    ]]
  },
  "properties": {
    "datetime": "2040-01-01T00:00:00Z",
    "start_datetime": "2040-01-01T00:00:00Z",
    "end_datetime": "2059-12-31T00:00:00Z",
    "title": "SPEI-12 Annual Mean — SSP3-7.0 Median (2040-2059)",
    "zarr:variables": ["spei12"],
    "zarr:dimensions": {"lat": 720, "lon": 1440},
    "ddh:dataset_id": "climate-spei12",
    "ddh:resource_id": "ssp370-median",
    "ddh:version_id": "v1",
    "ddh:access_level": "public"
  },
  "assets": {
    "zarr-store": {
      "href": "abfs://silver-zarr/climate-spei12/ssp370-median/store.zarr",
      "type": "application/vnd+zarr",
      "roles": ["data"],
      "title": "Zarr Store"
    }
  },
  "links": []
}
```

**Key differences from raster items**:
- Asset key is `zarr-store` (not `data`)
- Temporal range expressed via `start_datetime` / `end_datetime`
- `zarr:variables` and `zarr:dimensions` describe the array structure
- No TiTiler tile links (Zarr visualization uses a separate xarray endpoint)
- No `renders` or `raster:bands` (Zarr rendering is variable-based, not band-based)

### Example: Collection

The collection containing the DC aerial imagery item above:

```json
{
  "type": "Collection",
  "id": "dc-aerial-imagery",
  "stac_version": "1.0.0",
  "description": "High-resolution aerial imagery of Washington DC metropolitan area",
  "license": "proprietary",
  "extent": {
    "spatial": {
      "bbox": [[-77.028, 38.908, -77.013, 38.932]]
    },
    "temporal": {
      "interval": [["2024-06-15T00:00:00Z", null]]
    }
  },
  "links": [],
  "stac_extensions": [],
  "geo:iso3": ["USA"],
  "geo:primary_iso3": "USA",
  "geo:countries": ["United States"]
}
```

**Notes**:
- `extent.spatial.bbox` — union of all item bounding boxes, recalculated when items are added or removed
- `extent.temporal.interval` — `[earliest_datetime, latest_datetime]`; `null` end indicates an open-ended collection
- `license` — defaults to `"proprietary"`, configurable per collection
- `geo:*` — country-level attribution derived from the spatial extent

---

## Customization

The STAC schema supports extension. Additional properties can be added to items or collections without affecting existing consumers — custom classification tags, data quality indicators, domain-specific fields, or additional asset types.

Common extension patterns:
- **Custom properties**: Any `namespace:field_name` (e.g., `wb:sector`, `climate:scenario`)
- **Additional assets**: Multiple assets per item (e.g., data + metadata PDF + thumbnail)
- **Collection-level summaries**: Aggregate statistics across all items
- **Temporal precision**: Replacing sentinel dates with actual acquisition dates

Schema modifications can be discussed with the platform team.
