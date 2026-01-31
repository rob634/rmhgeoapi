# Epic E1: Vector Data as API

**Type**: Business
**Status**: Complete
**Last Updated**: 30 JAN 2026
**ADO Feature**: "Vector Data Pipeline"

---

## Value Statement

Transform vector geospatial files into queryable, tile-able datasets. Data publishers upload shapefiles/GeoJSON; consumers query via OGC Features API and view via vector tiles.

---

## Architecture

```
Source Data                  ETL (E7)                    Consumers (E6)
┌─────────────┐           ┌─────────────┐            ┌─────────────────┐
│ Shapefile   │           │ Docker      │            │ OGC Features    │
│ GeoJSON     │──────────▶│ Worker      │───────────▶│ (TiPG)          │
│ GeoPackage  │           │ (geopandas) │            ├─────────────────┤
└─────────────┘           └──────┬──────┘            │ Vector Tiles    │
                                 │                   │ (MVT via TiPG)  │
                                 ▼                   └─────────────────┘
                          ┌─────────────┐
                          │ PostGIS     │
                          │ + STAC Item │
                          └─────────────┘
```

**Key Principle**: All heavy processing (geopandas read, CRS transform, bulk SQL) runs in Docker Worker. FunctionApp handles job coordination and STAC registration.

---

## Features

| Feature | Status | Scope |
|---------|--------|-------|
| F1.1 Vector ETL Pipeline | ✅ | Source → PostGIS via geopandas + bulk COPY |
| F1.2 Vector STAC Registration | ✅ | STAC item with postgis:// asset link |
| F1.3 Vector Unpublish | ✅ | Drop table + delete STAC item |
| F1.4 OGC Features API | ✅ | Served by E6 (TiPG) |
| F1.5 Vector Tiles | ✅ | Served by E6 (TiPG MVT) |

---

## Feature Summaries

### F1.1: Vector ETL Pipeline
Three-stage pipeline:
1. **Prepare**: Read source with geopandas, validate geometry, transform CRS
2. **Upload**: Bulk insert to PostGIS using COPY protocol
3. **STAC**: Create STAC item with metadata

**Job**: `vector_docker_etl` (Docker Worker)

### F1.2: Vector STAC Registration
Every vector table gets a STAC item in pgSTAC with:
- `postgis://` asset link
- Bounding box from geometry
- Feature count, geometry type metadata
- Platform properties (dataset_id, resource_id, version_id)

### F1.3: Vector Unpublish
Cleanup operation to remove published data:
- Drop PostGIS table
- Delete STAC item
- Remove from `geo.table_catalog`

**Job**: `unpublish_vector`

### F1.4 & F1.5: Consumer APIs
Vector data is served to consumers via E6 Service Layer:
- OGC Features API: `/vector/collections/{id}/items`
- Vector Tiles (MVT): `/vector/collections/{id}/tiles/{z}/{x}/{y}`

---

## Dependencies

| Depends On | Enables |
|------------|---------|
| E7 Pipeline Infrastructure | Consumer access via E6 |
| PostgreSQL + PostGIS | H3 aggregation (E8) |

---

## Implementation Details

See `docs_claude/` for implementation specifics.
