# STAC Item & Collection Schema

**Last Updated**: 25 MAR 2026
**Audience**: Data owners and platform consumers (DDH integration team)
**Version**: v0.10.6 — Consolidated STAC schema

---

## What Is STAC?

STAC (SpatioTemporal Asset Catalog) is an open specification for describing geospatial data so it can be searched, discovered, and accessed programmatically. Think of it as a standardized metadata envelope around every dataset you publish.

Our platform uses STAC as the **discovery and access layer**. When data is processed and approved, it appears in the STAC catalog. Consumers query the catalog to find data, then access it through TiTiler (for visualization) or direct download.

**Key principle**: STAC items in our catalog are a **materialized view** of internal metadata. The catalog can be rebuilt from our internal database at any time. It contains only what consumers need — no internal plumbing.

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

A **Collection** groups related items. A **Item** represents one data resource (a file, a tile, a Zarr store) with its metadata and access URLs.

---

## What's In a STAC Item?

Every item in our catalog has this structure. Fields marked **(always)** are guaranteed present. Fields marked **(when available)** depend on what metadata the pipeline could extract.

### 1. Identity

| Field | Example | Notes |
|-------|---------|-------|
| `id` | `"jakarta-flood-depth-v1"` | Unique within the collection. Includes version for approved items. |
| `collection` | `"jakarta-flood-depth"` | Which collection this item belongs to. |
| `stac_version` | `"1.0.0"` | Always 1.0.0. |

### 2. Spatial Extent (always)

Every item has a bounding box and geometry in WGS84 (EPSG:4326):

```json
{
  "bbox": [-77.028, 38.908, -77.013, 38.932],
  "geometry": {
    "type": "Polygon",
    "coordinates": [[[-77.028, 38.908], [-77.013, 38.908], [-77.013, 38.932], [-77.028, 38.932], [-77.028, 38.908]]]
  }
}
```

This enables spatial search — "find all items that intersect this region."

### 3. Temporal (always)

| Field | Value | Notes |
|-------|-------|-------|
| `datetime` | `"2024-06-15T00:00:00Z"` | Acquisition or reference date, if known. |
| `datetime` | `"0001-01-01T00:00:00Z"` | Sentinel value meaning "date unknown." |
| `start_datetime` / `end_datetime` | Date range | For time-series data (e.g., Zarr stores covering 2020-2024). |

**Note**: Many raster datasets don't have embedded temporal information. When the date is unknown, we use `0001-01-01` as an unambiguous placeholder. If you know the correct date for your data, tell us and we'll set it.

### 4. Assets — How to Access the Data (always)

Assets are the actual data resources. Every item has at least one asset.

**For raster data (COG)**:
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

**For Zarr data**:
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

Every raster item includes links to TiTiler for live map rendering:

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

The **TileJSON** URL is the primary access mechanism. Point any web map (Leaflet, MapLibre, OpenLayers) at this URL to render the data as map tiles. No direct file access required.

For tiled collections (many tiles composited into one view), a **mosaic** search is registered, providing a single TileJSON URL that renders all tiles as one seamless layer.

### 6. Visualization Hints — Renders Extension (when available)

The `renders` property tells TiTiler how to visualize the data without manual configuration:

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

| Raster Type | Default Colormap | Example |
|-------------|-----------------|---------|
| DEM / elevation | `terrain` | Green lowlands, brown mountains, white peaks |
| Flood depth | `blues` | Light blue (shallow) to dark blue (deep) |
| Flood probability | `reds` | Light red (low) to dark red (high) |
| Vegetation index | `rdylgn` | Red (bare) to green (vegetated) |
| Population density | `ylorrd` | Yellow (sparse) to red (dense) |
| RGB imagery | Natural color | No colormap needed |

TiTiler reads these automatically — append `?render_id=default` to any TileJSON URL.

### 7. Projection (when available)

```json
{
  "proj:epsg": 4326,
  "proj:transform": [0.000003, 0.0, -77.028, 0.0, -0.000003, 38.932, 0.0, 0.0, 1.0]
}
```

The coordinate reference system and affine transform. Most data is reprojected to EPSG:4326 (WGS84) during processing. The original CRS is preserved here for consumers who need it.

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
| `ddh:dataset_id` | Maps to your DDH dataset. |
| `ddh:resource_id` | Maps to your DDH resource within the dataset. |
| `ddh:version_id` | Version identifier assigned at approval. |
| `ddh:access_level` | `"public"` or `"ouo"` (Official Use Only). Set at approval time. |

These fields appear only after the data is **approved** for publication.

### 9. Geographic Attribution (when available)

```json
{
  "geo:iso3": ["IDN"],
  "geo:primary_iso3": "IDN",
  "geo:countries": ["Indonesia"]
}
```

Country-level attribution derived from the item's bounding box. Enables queries like "show me all datasets for Indonesia."

### 10. Zarr-Specific Properties (Zarr items only)

```json
{
  "zarr:variables": ["temperature", "precipitation", "wind_speed"],
  "zarr:dimensions": {"time": 365, "lat": 720, "lon": 1440}
}
```

For Zarr stores, these describe the data variables and array dimensions.

---

## What's In a STAC Collection?

Collections are simpler — they describe the group, not individual items:

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

The spatial and temporal extent is the **union** of all items in the collection — it's recomputed whenever items are added or removed.

---

## STAC Extensions We Use

Extensions add standardized fields beyond the core STAC spec:

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
4. APPROVE     Data owner or reviewer approves the release
               Platform refs (ddh:*) and access level stamped
                  |
5. MATERIALIZE Item written to pgSTAC catalog
               TiTiler URLs injected
               Collection extent updated
                  |
6. DISCOVER    Item visible via STAC API
               TiTiler serves map tiles
```

Items are **not visible** in the STAC catalog until approved. Before approval, the metadata exists only in our internal database.

---

## Complete Examples

### Example: Raster COG Item (Single File)

This is a real item from our catalog — a 3-band RGB aerial image of Washington DC, approved for public access:

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
      "href": "https://rmhtitiler-.../cog/preview.png?url=%2Fvsiaz%2Fsilver-cogs%2Fdc-aerial%2F...",
      "type": "image/png",
      "roles": ["thumbnail"]
    }
  },
  "links": [
    {
      "rel": "tiles",
      "href": "https://rmhtitiler-.../cog/WebMercatorQuad/tilejson.json?url=%2Fvsiaz%2Fsilver-cogs%2Fdc-aerial%2F...",
      "type": "application/json",
      "title": "TileJSON"
    }
  ]
}
```

**What a consumer does with this**:
1. Read `assets.data.raster:bands` to understand band structure (3-band RGB, uint8)
2. Use `links[rel=tiles].href` to render on a map
3. Use `assets.thumbnail.href` for a quick preview
4. Use `properties.renders.default` to know TiTiler can auto-visualize as natural color
5. Use `ddh:dataset_id` / `ddh:resource_id` to link back to DDH metadata

### Example: Zarr Store Item (Climate Time-Series)

A Zarr store containing SPEI-12 drought index projections:

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

**Key differences from raster**:
- Asset key is `zarr-store` (not `data`)
- Has `start_datetime` / `end_datetime` for the temporal range
- `zarr:variables` and `zarr:dimensions` describe the array structure
- No TiTiler links (Zarr visualization uses a different TiTiler endpoint)
- No `renders` or `raster:bands` (Zarr rendering is variable-based, not band-based)

### Example: Collection

The collection that contains the DC aerial imagery item above:

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
- `extent.spatial.bbox` is the union of all item bounding boxes (recalculated when items are added/removed)
- `extent.temporal.interval` is `[earliest_datetime, latest_datetime]` — `null` end means "open-ended" (more items may be added)
- `license` defaults to `"proprietary"` — can be changed per collection
- `geo:*` attribution is derived from the spatial extent

---

## Customization

The STAC schema is designed to be extended. If you need additional properties on your items or collections — for example, custom classification tags, data quality indicators, or domain-specific fields — we can add them. STAC's extension mechanism means we can add fields without breaking existing consumers.

Common requests:
- **Custom properties**: Add any `namespace:field_name` to items (e.g., `wb:sector`, `climate:scenario`)
- **Additional assets**: Multiple assets per item (e.g., data + metadata PDF + thumbnail)
- **Collection-level summaries**: Aggregate statistics across all items
- **Temporal precision**: Replace sentinel dates with actual acquisition dates

Talk to the platform team about what you need.
