# Epic E2: Raster Data as API

**Type**: Business
**Status**: Complete
**Last Updated**: 30 JAN 2026
**ADO Feature**: "Raster Data Pipeline"

---

## Value Statement

Transform raster geospatial files into cloud-optimized, tile-able datasets. Data publishers upload GeoTIFFs; consumers access via dynamic tiles and point queries.

---

## Architecture

```
Source Data                  ETL (E7)                    Consumers (E6)
┌─────────────┐           ┌─────────────┐            ┌─────────────────┐
│ GeoTIFF     │           │ Docker      │            │ COG Tiles       │
│ (any size)  │──────────▶│ Worker      │───────────▶│ (TiTiler)       │
└─────────────┘           │ (GDAL)      │            ├─────────────────┤
                          └──────┬──────┘            │ Point Queries   │
                                 │                   │ (TiTiler)       │
                                 ▼                   ├─────────────────┤
                          ┌─────────────┐            │ pgSTAC Mosaics  │
                          │ COG (Azure) │            │ (TiTiler)       │
                          │ + STAC Item │            └─────────────────┘
                          └─────────────┘
```

**Key Principle**: All GDAL operations (COG creation, validation, metadata extraction) run in Docker Worker. Large rasters (>1GB) use tiling pipeline.

---

## Features

| Feature | Status | Scope |
|---------|--------|-------|
| F2.1 Raster ETL Pipeline | ✅ | Source → COG via GDAL |
| F2.2 Large Raster Pipeline | ✅ | Tiling for files >1GB |
| F2.3 Raster STAC Registration | ✅ | STAC item + app.cog_metadata |
| F2.4 Raster Unpublish | ✅ | Delete blob + STAC item |
| F2.5 COG Tile Serving | ✅ | Served by E6 (TiTiler) |
| F2.6 Point Queries | ✅ | Served by E6 (TiTiler) |

---

## Feature Summaries

### F2.1: Raster ETL Pipeline
Three-stage pipeline for standard rasters:
1. **Validate**: Check format, size, CRS with GDAL
2. **Create COG**: Convert to Cloud Optimized GeoTIFF
3. **STAC**: Create STAC item, populate app.cog_metadata

**Job**: `process_raster_v2` (Docker Worker)

### F2.2: Large Raster Pipeline
Extended pipeline for files >1GB:
1. **List Files**: Inventory source files
2. **Generate Tiling Scheme**: Calculate tile grid
3. **Extract Tiles**: Create tile COGs in parallel
4. **Create MosaicJSON**: Build mosaic index
5. **Register STAC**: Create collection + items

**Job**: `process_large_raster` (Docker Worker)

### F2.3: Raster STAC Registration
Every COG gets:
- STAC item in pgSTAC with COG asset link
- Entry in `app.cog_metadata` for metadata queries
- Platform properties (dataset_id, resource_id, version_id)

### F2.4: Raster Unpublish
Cleanup operation:
- Delete blob from Azure Storage
- Delete STAC item
- Remove from `app.cog_metadata`

**Job**: `unpublish_raster`

### F2.5 & F2.6: Consumer APIs
Raster data is served to consumers via E6 Service Layer:
- COG Tiles: `/cog/tiles/{z}/{x}/{y}?url={cog_url}`
- Point Queries: `/cog/point/{lon}/{lat}?url={cog_url}`
- Mosaics: `/searches/{search_id}/tiles/{z}/{x}/{y}`

---

## Dependencies

| Depends On | Enables |
|------------|---------|
| E7 Pipeline Infrastructure | Consumer access via E6 |
| Azure Blob Storage | H3 aggregation (E8) |

---

## Implementation Details

See `docs_claude/RASTER_METADATA.md` for metadata architecture.
