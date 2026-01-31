# Epic E6: Service Layer (B2C APIs)

**Type**: Platform
**Status**: Complete
**Last Updated**: 30 JAN 2026
**ADO Feature**: "Consumer APIs (TiTiler/TiPG)"
**Repository**: `rmhtitiler`

---

## Value Statement

Provide external consumers with standards-based APIs for accessing geospatial data. Replaces ArcGIS Server with modern, cloud-native tile serving. This is the primary B2C interface for the geospatial platform.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     SERVICE LAYER (rmhtitiler)                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐          │
│   │ TiTiler         │   │ TiPG            │   │ STAC API        │          │
│   │                 │   │                 │   │                 │          │
│   │ • COG tiles     │   │ • OGC Features  │   │ • Collections   │          │
│   │ • Point queries │   │ • Vector tiles  │   │ • Items         │          │
│   │ • xarray tiles  │   │ • MVT           │   │ • Search        │          │
│   │ • pgSTAC mosaic │   │                 │   │                 │          │
│   └────────┬────────┘   └────────┬────────┘   └────────┬────────┘          │
│            │                     │                     │                    │
│            └─────────────────────┴─────────────────────┘                    │
│                                  │                                          │
│                                  ▼                                          │
│                    ┌─────────────────────────┐                              │
│                    │ PostgreSQL (pgSTAC)     │                              │
│                    │ Azure Blob Storage      │                              │
│                    └─────────────────────────┘                              │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Key Principle**: This is a READ-ONLY service. All data is created by E1/E2/E9 ETL pipelines. E6 provides the consumer-facing APIs.

---

## Features

| Feature | Status | Scope |
|---------|--------|-------|
| F6.1 COG Tile Serving | ✅ | Dynamic tiles from Cloud Optimized GeoTIFFs |
| F6.2 Vector Tiles & OGC Features | ✅ | MVT tiles + GeoJSON from PostGIS |
| F6.3 Multidimensional Data | ✅ | Zarr/NetCDF tiles via xarray |
| F6.4 pgSTAC Mosaic Searches | ✅ | Dynamic mosaics from STAC queries |
| F6.5 STAC API | ✅ | Collection/item browse and search |
| F6.6 Service Operations | ✅ | Health checks, auth, observability |

---

## Feature Summaries

### F6.1: COG Tile Serving (TiTiler)
Dynamic tile rendering for Cloud Optimized GeoTIFFs:
- `GET /cog/tiles/{z}/{x}/{y}` - XYZ tiles
- `GET /cog/point/{lon}/{lat}` - Point queries
- `GET /cog/preview` - Thumbnail generation

### F6.2: Vector Tiles & OGC Features (TiPG)
OGC-compliant vector data access:
- `GET /vector/collections/{id}/items` - GeoJSON features
- `GET /vector/collections/{id}/tiles/{z}/{x}/{y}` - MVT vector tiles

### F6.3: Multidimensional Data (TiTiler-xarray)
Tile serving for Zarr and NetCDF data:
- `GET /xarray/tiles/{z}/{x}/{y}` - XYZ tiles
- `GET /xarray/point/{lon}/{lat}` - Time-series at point

### F6.4: pgSTAC Mosaic Searches
Dynamic mosaics from STAC catalog queries:
- `POST /searches/register` - Register a mosaic search
- `GET /searches/{id}/tiles/{z}/{x}/{y}` - Tiles from search results

### F6.5: STAC API
Catalog browse and search:
- `GET /stac/collections` - List collections
- `GET /stac/collections/{id}/items` - List items
- `POST /stac/search` - Search with filters

### F6.6: Service Operations
Production infrastructure:
- Health probes (`/livez`, `/readyz`, `/health`)
- Azure Managed Identity authentication
- OpenTelemetry observability

---

## Consumer Audiences

| Audience | Primary APIs | Use Case |
|----------|-------------|----------|
| Web Developers | Tiles, Vector Tiles | MapLibre/Leaflet integration |
| Data Scientists | Point queries, xarray | Notebook analysis |
| GIS Analysts | OGC Features, STAC | Data discovery and download |

---

## ArcGIS Migration Path

E6 serves as ArcGIS Server replacement:

| ArcGIS Capability | E6 Equivalent |
|-------------------|---------------|
| MapServer (tiles) | `/cog/tiles/{z}/{x}/{y}` |
| FeatureServer (features) | `/vector/collections/{id}/items` |
| FeatureServer (tiles) | `/vector/collections/{id}/tiles` |
| ImageServer (mosaic) | `/searches/register` + tiles |

---

## Dependencies

| Depends On | Enabled By |
|------------|------------|
| pgSTAC (PostgreSQL) | E1, E2, E9 data pipelines |
| Azure Blob Storage | E2 COG storage |
| PostGIS | E1 vector storage |

---

## Implementation Details

E6 is implemented in a separate repository: `rmhtitiler`

See `docs_titiler/` for TiTiler-specific documentation.
