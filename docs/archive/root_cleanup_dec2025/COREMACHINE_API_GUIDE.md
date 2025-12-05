# CoreMachine API Guide - Job Submission

**Last Updated**: 20 NOV 2025
**Purpose**: API reference for submitting geospatial data processing jobs to CoreMachine

---

## Overview

CoreMachine processes geospatial data through job-based workflows. Each job type handles specific data formats and processing pipelines.

**Base URL**: `https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net`

**Authentication**: None (internal system)

**Content-Type**: `application/json`

---

## Job Types

### 1. Ingest Vector (`ingest_vector`)

**Endpoint**: `POST /api/jobs/submit/ingest_vector`

**Purpose**: Load vector files from Azure Blob Storage to PostGIS with parallel chunked uploads and automatic STAC cataloging.

**Supported Formats** (6 total):
- CSV (lat/lon columns or WKT geometry)
- GeoJSON (`.geojson`, `.json`)
- GeoPackage (`.gpkg`)
- KML (`.kml`)
- KMZ (`.kmz` - zipped KML)
- Shapefile (`.shp`, `.zip`)

**Workflow** (3 stages):
1. **Stage 1**: Load file, validate geometries, chunk data, pickle to blob storage (single task)
2. **Stage 2**: Upload chunks to PostGIS in parallel (N tasks, fan-out pattern)
3. **Stage 3**: Create STAC metadata record for PostGIS table (single task)

#### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `blob_name` | string | Yes | - | Path to vector file in blob storage (e.g., `"data/parcels.geojson"`) |
| `file_extension` | string | Yes | - | File extension: `csv`, `geojson`, `json`, `gpkg`, `kml`, `kmz`, `shp`, `zip` |
| `table_name` | string | Yes | - | Target PostGIS table name (alphanumeric + underscore, starts with letter) |
| `container_name` | string | No | `rmhazuregeobronze` | Source blob storage container |
| `schema` | string | No | `geo` | Target PostgreSQL schema (`geo` or `public`) |
| `chunk_size` | integer | No | Auto-calculated | Rows per chunk (100-500,000). Auto-calculated based on file size if not provided |
| `converter_params` | object | No | `{}` | Format-specific parameters (see below) |
| `indexes` | object | No | See below | Database index configuration |
| `geometry_params` | object | No | `{}` | Geometry processing options (simplification, quantization) |
| `render_params` | object | No | `{}` | Reserved for future rendering optimizations |

#### converter_params (Format-Specific)

**CSV files**:
```json
{
  "converter_params": {
    "lat_name": "latitude",
    "lon_name": "longitude"
  }
}
```
OR for WKT geometry:
```json
{
  "converter_params": {
    "wkt_column": "geometry"
  }
}
```

**GeoPackage files**:
```json
{
  "converter_params": {
    "layer_name": "parcels"
  }
}
```

**KMZ/Shapefile** (zipped archives):
```json
{
  "converter_params": {
    "file_name": "parcels.shp"
  }
}
```

#### indexes (Database Index Configuration)

```json
{
  "indexes": {
    "spatial": true,
    "attributes": ["name", "category", "owner"],
    "temporal": ["created_date", "modified_date"]
  }
}
```

- `spatial` (boolean, default: `true`): Create GIST spatial index on geometry column
- `attributes` (array of strings, default: `[]`): Column names for B-tree indexes (frequently filtered attributes)
- `temporal` (array of strings, default: `[]`): Column names for DESC B-tree indexes (date/time columns)

#### geometry_params (Geometry Processing)

```json
{
  "geometry_params": {
    "simplify": {
      "tolerance": 0.0001,
      "preserve_topology": true
    },
    "quantize": {
      "snap_to_grid": 0.000001
    }
  }
}
```

**Simplification** (Douglas-Peucker algorithm):
- `tolerance` (float): Simplification tolerance in degrees (smaller = more detail)
- `preserve_topology` (boolean, default: `true`): Preserve topology during simplification

**Quantization** (Coordinate precision reduction):
- `snap_to_grid` (float): Grid size for coordinate snapping (reduces file size)

#### Example Request

**Minimal** (GeoJSON file):
```bash
curl -X POST 'https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/ingest_vector' \
  -H 'Content-Type: application/json' \
  -d '{
    "blob_name": "8.geojson",
    "file_extension": "geojson",
    "table_name": "test_dataset"
  }'
```

**Full** (CSV with geometry simplification and custom indexes):
```bash
curl -X POST 'https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/ingest_vector' \
  -H 'Content-Type: application/json' \
  -d '{
    "blob_name": "parcels/data.csv",
    "file_extension": "csv",
    "table_name": "city_parcels",
    "container_name": "rmhazuregeobronze",
    "schema": "geo",
    "chunk_size": 20000,
    "converter_params": {
      "lat_name": "latitude",
      "lon_name": "longitude"
    },
    "indexes": {
      "spatial": true,
      "attributes": ["parcel_id", "owner_name", "zoning"],
      "temporal": ["sale_date", "assessed_date"]
    },
    "geometry_params": {
      "simplify": {
        "tolerance": 0.0001,
        "preserve_topology": true
      }
    }
  }'
```

#### Response

**Success** (202 Accepted):
```json
{
  "job_id": "a3f7b2c1d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6",
  "status": "queued",
  "job_type": "ingest_vector",
  "message": "Job submitted successfully",
  "parameters": {
    "blob_name": "8.geojson",
    "file_extension": "geojson",
    "table_name": "test_dataset",
    "container_name": "rmhazuregeobronze",
    "schema": "geo",
    "chunk_size": null
  },
  "stages": {
    "current": 1,
    "total": 3
  },
  "created_at": "2025-11-20T22:00:00Z"
}
```

**Error** (400 Bad Request):
```json
{
  "error": "Bad request",
  "message": "Table geo.test_dataset already exists. To replace it, drop the table first:\n  DROP TABLE geo.test_dataset CASCADE;\nOr choose a different table_name.",
  "request_id": "45a21791",
  "timestamp": "2025-11-20T21:46:00.165891+00:00"
}
```

**Error** (404 Not Found):
```json
{
  "error": "Bad request",
  "message": "File 'data/missing.geojson' not found in container 'rmhazuregeobronze' (storage account: 'rmhazuregeo'). Verify file path or use /api/containers/rmhazuregeobronze/blobs to list available files.",
  "request_id": "b6d32c14",
  "timestamp": "2025-11-20T21:50:00.123456+00:00"
}
```

#### Output

**API Endpoints Generated**:
- **OGC API - Features**: `https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/features/collections/{table_name}/items`
- **Vector Viewer**: `https://rmhazuregeo.z13.web.core.windows.net/?collection={table_name}`

**Database Storage**:
- Table created in PostgreSQL: `{schema}.{table_name}` (default: `geo.{table_name}`)
- Geometry column: `geom` (PostGIS GEOMETRY type, SRID 4326)
- Indexes: GIST spatial index + optional B-tree indexes on attributes

**STAC Metadata**:
- STAC item created in `pgstac.items` (if pgSTAC installed)
- Collection: `system-vectors`

---

### 2. Process Raster (`process_raster`)

**Endpoint**: `POST /api/jobs/submit/process_raster`

**Purpose**: Convert single raster file to Cloud-Optimized GeoTIFF (COG) with compression, overviews, and automatic STAC cataloging.

**Supported Formats**:
- GeoTIFF (`.tif`, `.tiff`)
- Any GDAL-readable raster format

**Workflow** (2-3 stages):
1. **Stage 1**: Validate raster, check CRS, create COG with compression and overviews
2. **Stage 2** (optional): Tile large rasters into smaller COGs (if raster exceeds size threshold)
3. **Stage 3**: Create STAC metadata record and validate TiTiler access

#### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `blob_name` | string | Yes | - | Path to raster file in blob storage (e.g., `"elevation/dem.tif"`) |
| `file_extension` | string | Yes | - | File extension: `tif`, `tiff` |
| `output_name` | string | No | Auto-generated | Output COG filename (without extension) |
| `container_name` | string | No | `rmhazuregeobronze` | Source blob storage container |
| `output_container` | string | No | `api-data` | Target blob storage container for COG output |
| `compression` | string | No | Auto-detected | Compression algorithm: `JPEG`, `DEFLATE`, `LZW`, `ZSTD` |
| `quality` | integer | No | 85 | JPEG compression quality (1-100, only for JPEG compression) |
| `blocksize` | integer | No | 512 | Internal tile size (256, 512, 1024) |
| `overview_levels` | array | No | Auto-generated | Overview levels (e.g., `[2, 4, 8, 16]`) |
| `reproject_to` | string | No | Source CRS | Target CRS for reprojection (e.g., `"EPSG:3857"`, `"EPSG:4326"`) |
| `nodata_value` | number | No | Source nodata | Nodata value to use in output COG |

#### Example Request

**Minimal** (auto-detect compression):
```bash
curl -X POST 'https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/process_raster' \
  -H 'Content-Type: application/json' \
  -d '{
    "blob_name": "elevation/dem.tif",
    "file_extension": "tif"
  }'
```

**Full** (custom compression and reprojection):
```bash
curl -X POST 'https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/process_raster' \
  -H 'Content-Type: application/json' \
  -d '{
    "blob_name": "imagery/sentinel2_2024.tif",
    "file_extension": "tif",
    "output_name": "sentinel2_2024_cog",
    "container_name": "rmhazuregeobronze",
    "output_container": "api-data",
    "compression": "JPEG",
    "quality": 90,
    "blocksize": 512,
    "overview_levels": [2, 4, 8, 16, 32],
    "reproject_to": "EPSG:3857",
    "nodata_value": 0
  }'
```

#### Compression Options

**Auto-detection logic** (if `compression` not specified):
- **RGB imagery** (uint8/uint16, 3 bands): `JPEG` (lossy, 10x smaller files)
- **Elevation/continuous data** (float32/float64): `DEFLATE` (lossless, good compression)
- **Categorical/general**: `LZW` (lossless, universal compatibility)

**Manual compression options**:
- `JPEG`: Lossy, best for RGB imagery (85-95 quality recommended)
- `DEFLATE`: Lossless, best for DEMs and float data (use with predictor=3)
- `LZW`: Lossless, universal compatibility
- `ZSTD`: Lossless, best compression ratio (requires recent GDAL)

#### Response

**Success** (202 Accepted):
```json
{
  "job_id": "b8e9c3f4a5d6e7f8g9h0i1j2k3l4m5n6o7p8q9r0s1t2u3v4w5x6y7",
  "status": "queued",
  "job_type": "process_raster",
  "message": "Job submitted successfully",
  "parameters": {
    "blob_name": "elevation/dem.tif",
    "file_extension": "tif",
    "container_name": "rmhazuregeobronze",
    "output_container": "api-data",
    "compression": "DEFLATE",
    "blocksize": 512
  },
  "stages": {
    "current": 1,
    "total": 3
  },
  "created_at": "2025-11-20T22:05:00Z"
}
```

#### Output

**COG File**:
- Storage location: `{output_container}/{output_name}.tif`
- Format: Cloud-Optimized GeoTIFF with internal tiling, compression, and overviews
- Web-optimized: Supports HTTP range requests for partial reads

**API Endpoints Generated**:
- **TiTiler Tiles**: `https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/tiles/cog/tiles/{z}/{x}/{y}?url={cog_url}`
- **TiTiler Info**: `https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/tiles/cog/info?url={cog_url}`
- **TiTiler Statistics**: `https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/tiles/cog/statistics?url={cog_url}`

**STAC Metadata**:
- STAC item created in `pgstac.items` (if pgSTAC installed)
- Contains COG asset reference and TiTiler tile endpoint

---

### 3. Process Raster Collection (`process_raster_collection`)

**Endpoint**: `POST /api/jobs/submit/process_raster_collection`

**Purpose**: Convert multiple raster files to COGs and create STAC Collection with mosaicking support via TiTiler-pgSTAC.

**Supported Formats**: Same as `process_raster`

**Workflow** (3 stages):
1. **Stage 1**: Validate all rasters in collection
2. **Stage 2**: Convert each raster to COG in parallel (fan-out pattern)
3. **Stage 3**: Create STAC Collection and Items, enable TiTiler-pgSTAC mosaicking

#### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `blob_prefix` | string | Yes | - | Blob storage prefix (folder path) containing rasters (e.g., `"sentinel2/2024/"`) |
| `file_extension` | string | Yes | - | File extension to match: `tif`, `tiff` |
| `collection_id` | string | Yes | - | STAC Collection ID (alphanumeric + hyphen + underscore) |
| `collection_name` | string | No | Same as `collection_id` | Human-readable collection name |
| `collection_description` | string | No | Auto-generated | Collection description for STAC metadata |
| `container_name` | string | No | `rmhazuregeobronze` | Source blob storage container |
| `output_container` | string | No | `api-data` | Target blob storage container for COG outputs |
| `compression` | string | No | Auto-detected | Compression for all COGs (see `process_raster`) |
| `quality` | integer | No | 85 | JPEG quality for all COGs (if JPEG compression) |
| `blocksize` | integer | No | 512 | Internal tile size for all COGs |
| `temporal_extent` | object | No | Auto-detected | Temporal extent for STAC Collection |

#### temporal_extent

```json
{
  "temporal_extent": {
    "start_date": "2024-01-01T00:00:00Z",
    "end_date": "2024-12-31T23:59:59Z"
  }
}
```

#### Example Request

**Minimal** (process all `.tif` files in folder):
```bash
curl -X POST 'https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/process_raster_collection' \
  -H 'Content-Type: application/json' \
  -d '{
    "blob_prefix": "sentinel2/2024/",
    "file_extension": "tif",
    "collection_id": "sentinel2-2024"
  }'
```

**Full** (custom compression and metadata):
```bash
curl -X POST 'https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/process_raster_collection' \
  -H 'Content-Type: application/json' \
  -d '{
    "blob_prefix": "landsat8/california/",
    "file_extension": "tif",
    "collection_id": "landsat8-california",
    "collection_name": "Landsat 8 - California",
    "collection_description": "Landsat 8 imagery for California region, 2024",
    "container_name": "rmhazuregeobronze",
    "output_container": "api-data",
    "compression": "JPEG",
    "quality": 90,
    "blocksize": 512,
    "temporal_extent": {
      "start_date": "2024-01-01T00:00:00Z",
      "end_date": "2024-12-31T23:59:59Z"
    }
  }'
```

#### Response

**Success** (202 Accepted):
```json
{
  "job_id": "c9d0e1f2a3b4c5d6e7f8g9h0i1j2k3l4m5n6o7p8q9r0s1t2u3v4w5",
  "status": "queued",
  "job_type": "process_raster_collection",
  "message": "Job submitted successfully",
  "parameters": {
    "blob_prefix": "sentinel2/2024/",
    "file_extension": "tif",
    "collection_id": "sentinel2-2024",
    "container_name": "rmhazuregeobronze",
    "output_container": "api-data",
    "compression": "JPEG"
  },
  "stages": {
    "current": 1,
    "total": 3
  },
  "files_discovered": 127,
  "created_at": "2025-11-20T22:10:00Z"
}
```

#### Output

**COG Files**:
- Storage location: `{output_container}/{collection_id}/{filename}.tif` (one COG per source raster)
- All COGs have consistent compression, blocksize, and CRS

**API Endpoints Generated**:
- **STAC Collection**: `https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/collections/{collection_id}`
- **STAC Items**: `https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/collections/{collection_id}/items`
- **TiTiler-pgSTAC Mosaic**: `https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/tiles/searches/{collection_id}/tiles/{z}/{x}/{y}`

**STAC Metadata**:
- STAC Collection created in `pgstac.collections`
- STAC Items created in `pgstac.items` (one per COG)
- TiTiler-pgSTAC can dynamically mosaic all items in collection based on STAC search query

---

## Checking Job Status

**Endpoint**: `GET /api/jobs/status/{job_id}`

**Example**:
```bash
curl 'https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/status/{job_id}'
```

**Response** (In Progress):
```json
{
  "job_id": "a3f7b2c1d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6",
  "job_type": "ingest_vector",
  "status": "processing",
  "stage": 2,
  "total_stages": 3,
  "progress": {
    "current_stage": 2,
    "stage_name": "upload_chunks",
    "tasks_completed": 45,
    "tasks_total": 129,
    "percent_complete": 34.9
  },
  "created_at": "2025-11-20T22:00:00Z",
  "updated_at": "2025-11-20T22:02:15Z"
}
```

**Response** (Completed):
```json
{
  "job_id": "a3f7b2c1d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6",
  "job_type": "ingest_vector",
  "status": "completed",
  "stage": 3,
  "total_stages": 3,
  "result_data": {
    "table_name": "test_dataset",
    "schema": "geo",
    "total_rows_uploaded": 2500000,
    "chunks_uploaded": 129,
    "chunks_failed": 0,
    "data_complete": true,
    "ogc_features_url": "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/features/collections/test_dataset/items",
    "viewer_url": "https://rmhazuregeo.z13.web.core.windows.net/?collection=test_dataset",
    "stac": {
      "collection_id": "system-vectors",
      "stac_id": "a3f7b2c1-dataset",
      "feature_count": 2500000,
      "bbox": [-180, -90, 180, 90]
    }
  },
  "created_at": "2025-11-20T22:00:00Z",
  "updated_at": "2025-11-20T22:17:30Z",
  "duration_seconds": 1050
}
```

---

## Error Handling

### Common Errors

**Table Already Exists** (400):
```json
{
  "error": "Bad request",
  "message": "Table geo.parcels already exists. To replace it, drop the table first:\n  DROP TABLE geo.parcels CASCADE;\nOr choose a different table_name."
}
```

**File Not Found** (404):
```json
{
  "error": "Bad request",
  "message": "File 'data/missing.geojson' not found in container 'rmhazuregeobronze' (storage account: 'rmhazuregeo'). Verify file path or use /api/containers/rmhazuregeobronze/blobs to list available files."
}
```

**Container Not Found** (404):
```json
{
  "error": "Bad request",
  "message": "Container 'wrongcontainer' does not exist in storage account 'rmhazuregeo'. Verify container name spelling."
}
```

**Invalid Parameters** (400):
```json
{
  "error": "Bad request",
  "message": "file_extension 'pdf' not supported. Supported: csv, geojson, json, gpkg, kml, kmz, shp, zip"
}
```

**Job Already Running** (409 Conflict):
```json
{
  "error": "Conflict",
  "message": "Job with same parameters already exists (job_id: a3f7b2c1...). Status: processing. Use GET /api/jobs/status/{job_id} to check progress."
}
```

---

## Helper Endpoints

### List Blobs in Container

**Endpoint**: `GET /api/containers/{container_name}/blobs?prefix={prefix}`

**Example**:
```bash
curl 'https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/containers/rmhazuregeobronze/blobs?prefix=data/'
```

**Response**:
```json
{
  "container": "rmhazuregeobronze",
  "prefix": "data/",
  "blobs": [
    {
      "name": "data/parcels.geojson",
      "size_bytes": 45678901,
      "size_mb": 43.55,
      "last_modified": "2025-11-15T14:30:00Z"
    },
    {
      "name": "data/buildings.gpkg",
      "size_bytes": 123456789,
      "size_mb": 117.74,
      "last_modified": "2025-11-18T09:15:00Z"
    }
  ],
  "total_blobs": 2,
  "total_size_mb": 161.29
}
```

### Get Detailed Job Results

**Endpoint**: `GET /api/db/jobs/{job_id}`

**Example**:
```bash
curl 'https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/db/jobs/{job_id}'
```

**Response**: Full job record including all task results, stage results, and execution metadata

---

## Performance Considerations

### Vector Ingestion

**Chunking Strategy**:
- Default chunk size: Auto-calculated based on file size and available memory
- Manual chunk size: 100-500,000 rows per chunk
- Optimal for production: 10,000-20,000 rows per chunk

**Performance Metrics** (Production Scale):
- 2.5M rows, 129 chunks, 20 concurrent tasks: ~15 minutes
- Chunking overhead: Minimal (uses pickle serialization to blob storage)
- PostGIS insert rate: ~2,800 rows/second per task

### Raster Processing

**COG Optimization**:
- Blocksize: 512x512 (optimal for web serving and storage)
- Compression: Auto-detection based on data type
- Overview generation: Automatic pyramid levels for zoom performance

**Processing Time**:
- Single 10GB GeoTIFF → COG: ~5-10 minutes
- 100-file collection: ~30-60 minutes (parallel processing)

---

## Notes

1. **Idempotency**: Job IDs are SHA256 hashes of parameters. Submitting the same parameters returns the existing job.

2. **Table Validation**: `ingest_vector` checks if table exists before submission. Drop existing tables first or choose a different table name.

3. **Blob Validation**: Both `ingest_vector` and `process_raster` validate that source files exist before queuing. Use `/api/containers/{container}/blobs` to list available files.

4. **STAC Integration**: All jobs create STAC metadata records (requires pgSTAC installed via `/api/stac/setup`).

5. **Fan-Out Parallelism**: Vector uploads and raster collections use fan-out patterns for parallel processing. Maximum concurrency controlled by Service Bus `maxConcurrentCalls` setting.

6. **Error Recovery**: Failed tasks are retried automatically (up to 3 times). Check `result_data.failed_chunks_detail` for chunk-level error diagnostics.

7. **Output URLs**: All jobs generate API endpoint URLs (OGC Features, TiTiler, STAC) for immediate data access.