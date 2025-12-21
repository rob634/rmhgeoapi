# API Job Submission Guide

> **Navigation**: [Quick Start](WIKI_QUICK_START.md) | [Platform API](WIKI_PLATFORM_API.md) | [All Jobs](WIKI_API_JOB_SUBMISSION.md) | [Errors](WIKI_API_ERRORS.md) | [Glossary](WIKI_API_GLOSSARY.md)

**Date**: 27 NOV 2025
**Purpose**: Quick reference for submitting jobs via REST API
**Wiki**: Azure DevOps Wiki - API reference documentation

**Important**: This document includes admin/maintenance endpoints with destructive operations. These endpoints (schema redeploy, STAC nuke, etc.) are for development and testing only. See the [Admin and Maintenance section](#admin-and-maintenance-endpoints-devtest-only) for full safety warnings.

---

## Two API Patterns: CoreMachine vs Platform

This application provides **two ways to submit geospatial processing jobs**, designed for different use cases:

### CoreMachine API (Direct) - Power Users and Internal Tools

**Pattern**: `/api/jobs/submit/{job_type}`

**Who uses it**: Developers, internal tools, power users who understand the system internals

**Characteristics**:
- Direct access to CoreMachine job orchestration engine
- Requires knowledge of CoreMachine job parameters (blob paths, container names, etc.)
- Full flexibility and control over all job parameters
- Idempotent job IDs based on SHA256 hash of parameters
- Status queries via `/api/jobs/status/{job_id}`

**Use when**: You're building internal tools, scripts, or have deep knowledge of the system

---

### Platform API (DDH Integration) - External Applications

**Pattern**: `/api/platform/request`

**Who uses it**: DDH (Development Data Hub), external applications, non-technical users

**Characteristics**:
- Anti-Corruption Layer (ACL) that translates external identifiers to CoreMachine parameters
- Uses high-level identifiers: `dataset_id`, `resource_id`, `version_id` (DDH standard)
- Automatically generates output paths, table names, STAC IDs from DDH identifiers
- Idempotent request IDs based on SHA256 hash of DDH identifiers
- Status queries via `/api/platform/status/{request_id}`
- Shields external applications from CoreMachine internal changes

**Use when**: Integrating with DDH or building external applications that shouldn't know CoreMachine internals

**Key Benefit**: DDH API changes are absorbed in Platform layer without touching CoreMachine jobs

---

### Quick Comparison

| Feature | CoreMachine API | Platform API |
|---------|----------------|--------------|
| **Audience** | Internal developers | External applications (DDH) |
| **Identifiers** | `job_id` (SHA256 of params) | `request_id` (SHA256 of DDH IDs) |
| **Parameters** | CoreMachine-specific (blob_name, table_name) | DDH-specific (dataset_id, resource_id, version_id) |
| **Output Naming** | You specify table/collection names | Auto-generated from DDH identifiers |
| **Status Endpoint** | `/api/jobs/status/{job_id}` | `/api/platform/status/{request_id}` |
| **Use Case** | Internal automation, scripts | DDH integration, external apps |

---

## Base URL

```
https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net
```

---

## CoreMachine API - Direct Job Submission

**Pattern for power users and internal tools:**

```bash
POST /api/jobs/submit/{job_type}
Content-Type: application/json

{
  "parameter1": "value1",
  "parameter2": "value2"
}
```

**Response**:
```json
{
  "job_id": "sha256_hash_of_params",
  "status": "created",
  "job_type": "job_name",
  "message": "Job created and queued for processing",
  "parameters": { ... },
  "queue_info": {
    "queued": true,
    "queue_type": "service_bus",
    "queue_name": "geospatial-jobs",
    "message_id": "uuid"
  }
}
```

---

## Check Job Status

```bash
GET /api/jobs/status/{job_id}
```

**Example**:
```bash
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}
```

**Response**:
```json
{
  "jobId": "job_id_hash",
  "jobType": "job_name",
  "status": "completed",  // queued, processing, completed, failed, completed_with_errors
  "stage": 2,
  "totalStages": 2,
  "parameters": { ... },
  "resultData": { ... },
  "createdAt": "2025-11-21T04:49:17.020901",
  "updatedAt": "2025-11-21T04:49:20.714439"
}
```

---

## Available Jobs

Current job types (as of 13 DEC 2025):
- `hello_world` - Simple test job
- `process_vector` - **RECOMMENDED** Idempotent vector data ingestion to PostGIS (CSV, GeoJSON, Shapefile, GeoPackage, KML, KMZ)
- `process_raster_v2` - Single raster to COG conversion (≤800 MB files)
- `process_raster_collection_v2` - Multi-raster collection processing (≤20 files, each ≤800 MB)
- `process_large_raster_v2` - Large raster tiling and COG conversion (100 MB - 30 GB files)
- `validate_raster_job` - Raster validation
- `stac_catalog_container` - STAC catalog for blob container
- `stac_catalog_vectors` - STAC catalog for vector data
- `summarize_container` - Blob container summary
- `list_container_contents` - List blob container contents
- `list_container_contents_diamond` - Diamond pattern container listing
- `create_h3_base` - Create H3 grid base
- `generate_h3_level4` - Generate H3 level 4 grid
- `bootstrap_h3_land_grid_pyramid` - Bootstrap H3 land grid pyramid

---

## 1. Hello World Job

**Purpose**: Simple test job to verify system is operational

**Job Type**: `hello_world`

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `message` | string | No | "Hello from Azure Functions!" | Custom message to echo |
| `n` | integer | No | 1 | Number of parallel tasks to create |
| `failure_rate` | float | No | 0.0 | Simulated failure rate (0.0-1.0) for testing |

### Examples

**Simple hello world**:
```bash
curl -X POST \
  https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/hello_world \
  -H 'Content-Type: application/json' \
  -d '{
    "message": "Testing config deployment"
  }'
```

**With parallelism (n=5 tasks)**:
```bash
curl -X POST \
  https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/hello_world \
  -H 'Content-Type: application/json' \
  -d '{
    "message": "Parallel test",
    "n": 5
  }'
```

**With simulated failures (testing error handling)**:
```bash
curl -X POST \
  https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/hello_world \
  -H 'Content-Type: application/json' \
  -d '{
    "message": "Failure test",
    "n": 10,
    "failure_rate": 0.3
  }'
```

### Response Time
- Typical: 2-5 seconds for n=1-5
- High parallelism (n=100): 15-30 seconds

### Use Cases
- Verify deployment successful
- Test queue processing
- Validate database connectivity
- Test parallel task execution
- Simulate failure scenarios

---

## 2. Process Vector Job

**Purpose**: Load vector data into PostGIS with idempotent-by-design workflow

**Job Type**: `process_vector`

**Status**: **PRODUCTION READY** - Idempotent vector ingestion (28 NOV 2025)

**Key Features**:
- Built-in idempotency via DELETE+INSERT pattern with `etl_batch_id` tracking
- Retry-safe: no duplicate rows on task retries
- Pre-flight validation: fails fast if source blob doesn't exist (HTTP 400)
- Supports CSV, GeoJSON, Shapefile, GeoPackage, KML, KMZ

---

### CoreMachine API (Direct)

Direct submission when you know the exact table name and parameters.

#### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `blob_name` | string | **Yes** | - | Source file path in blob container |
| `file_extension` | string | **Yes** | - | File type: `csv`, `geojson`, `json`, `gpkg`, `kml`, `kmz`, `shp`, `zip` |
| `table_name` | string | **Yes** | - | Target PostGIS table name (will be created) |
| `container_name` | string | No | "rmhazuregeobronze" | Source blob container |
| `schema` | string | No | "geo" | PostgreSQL schema for table |
| `chunk_size` | integer | No | Auto | Rows per chunk (100-500000, auto-calculated if not specified) |
| `converter_params` | dict | No | {} | File-specific conversion parameters |
| `geometry_params` | dict | No | {} | Geometry processing options |
| `indexes` | dict | No | See below | Index configuration |

#### Converter Parameters by File Type

**CSV files** (required for CSV):
```json
{
  "converter_params": {
    "lat_name": "latitude",    // Column name containing latitude
    "lon_name": "longitude"    // Column name containing longitude
  }
}
```
OR for WKT geometry column:
```json
{
  "converter_params": {
    "wkt_column": "geometry"   // Column name containing WKT geometry
  }
}
```

**GeoPackage files** (optional):
```json
{
  "converter_params": {
    "layer_name": "my_layer"   // Specific layer to extract (optional, uses first layer by default)
  }
}
```

**KMZ files** (optional):
```json
{
  "converter_params": {
    "kml_name": "doc.kml"      // Specific KML file in archive (optional, uses first .kml found)
  }
}
```

**Shapefile/ZIP** (optional):
```json
{
  "converter_params": {
    "shp_name": "data.shp"     // Specific .shp file in archive (optional, uses first .shp found)
  }
}
```

#### Indexes Configuration

Default indexes:
```json
{
  "spatial": true,         // GIST index on geometry column
  "attributes": [],        // B-tree indexes on attribute columns
  "temporal": []          // DESC B-tree indexes on temporal columns
}
```

Example with custom indexes:
```json
{
  "spatial": true,
  "attributes": ["country_code", "admin1_name"],
  "temporal": ["event_date"]
}
```

---

### CoreMachine Examples

**CSV with lat/lon columns** (27 NOV 2025 - verified with ACLED 2.57M rows):
```bash
curl -X POST \
  https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/process_vector \
  -H 'Content-Type: application/json' \
  -d '{
    "blob_name": "acled_export.csv",
    "file_extension": "csv",
    "table_name": "acled_events",
    "chunk_size": 20000,
    "converter_params": {
      "lat_name": "latitude",
      "lon_name": "longitude"
    }
  }'
```

**Results** (ACLED conflict data - 2.57M rows):
| Metric | Value |
|--------|-------|
| Status | `completed` |
| Total Features | 2,570,844 |
| Chunks | 129 (20,000 rows each) |
| Parallelism | 32 workers (4 processes × 8 concurrent) |
| Duration | ~8 minutes |

**GeoJSON ingestion**:
```bash
curl -X POST \
  https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/process_vector \
  -H 'Content-Type: application/json' \
  -d '{
    "blob_name": "boundaries.geojson",
    "file_extension": "geojson",
    "table_name": "admin_boundaries"
  }'
```

**Shapefile (zipped)** (27 NOV 2025 - verified with roads.zip):
```bash
curl -X POST \
  https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/process_vector \
  -H 'Content-Type: application/json' \
  -d '{
    "blob_name": "roads.zip",
    "file_extension": "shp",
    "table_name": "roads_network"
  }'
```

**GeoPackage ingestion**:
```bash
curl -X POST \
  https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/process_vector \
  -H 'Content-Type: application/json' \
  -d '{
    "blob_name": "data.gpkg",
    "file_extension": "gpkg",
    "table_name": "gpkg_features"
  }'
```

**KML ingestion**:
```bash
curl -X POST \
  https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/process_vector \
  -H 'Content-Type: application/json' \
  -d '{
    "blob_name": "locations.kml",
    "file_extension": "kml",
    "table_name": "kml_locations"
  }'
```

**KMZ ingestion**:
```bash
curl -X POST \
  https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/process_vector \
  -H 'Content-Type: application/json' \
  -d '{
    "blob_name": "routes.kmz",
    "file_extension": "kmz",
    "table_name": "kmz_routes"
  }'
```

**Large dataset with custom chunk size and indexes**:
```bash
curl -X POST \
  https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/process_vector \
  -H 'Content-Type: application/json' \
  -d '{
    "blob_name": "global_events.csv",
    "file_extension": "csv",
    "table_name": "global_events_v1",
    "chunk_size": 25000,
    "converter_params": {
      "lat_name": "lat",
      "lon_name": "lon"
    },
    "indexes": {
      "spatial": true,
      "attributes": ["country", "event_type", "source"],
      "temporal": ["event_date"]
    }
  }'
```

---

### Workflow Stages

**Stage 1**: Prepare Chunks (`process_vector_prepare`)
- Download source file from blob storage
- Convert to GeoDataFrame (CSV, GeoJSON, GPKG, KML, KMZ, Shapefile)
- Validate and clean geometry
- Create PostGIS table with `etl_batch_id` column (idempotent - IF NOT EXISTS)
- Chunk data based on chunk_size
- Pickle chunks to blob storage (idempotent - overwrite=True)
- Duration: 10-120 seconds (depends on file size)

**Stage 2**: Upload Chunks (`process_vector_upload`) - Fan-out
- N parallel tasks (one per chunk)
- Each task uses DELETE+INSERT pattern:
  1. DELETE all rows WHERE etl_batch_id = batch_id
  2. INSERT new rows with that batch_id
- Atomic transaction per chunk (no partial data on failure)
- **Idempotent**: Re-running same task deletes previous attempt first
- Duration: 5-120 seconds (depends on chunk count and concurrency)

**Stage 3**: STAC Cataloging (`create_vector_stac`)
- Query PostGIS table for metadata (bbox, feature count)
- Create/update STAC item in pgstac
- Generate OGC Features API URL
- Generate Vector Viewer URL
- Duration: 2-5 seconds

---

### Idempotency Mechanism

The `process_vector` workflow is idempotent **by design**, not by configuration:

1. **Table Creation**: Uses `CREATE TABLE IF NOT EXISTS` (safe to re-run)
2. **Pickle Storage**: Uses `overwrite=True` (safe to re-run)
3. **Chunk Upload**: Uses DELETE+INSERT pattern with `etl_batch_id`:
   - Each chunk has unique ID: `{job_id[:8]}-chunk-{index}`
   - DELETE removes any existing rows with that batch_id
   - INSERT adds fresh data with same batch_id
   - Single transaction ensures atomic success/failure
4. **STAC Catalog**: Checks if item exists before insert

**Result**: You can safely retry failed jobs or tasks without creating duplicate data.

**Idempotency Metrics in Result**:
```json
{
  "summary": {
    "total_rows_inserted": 2570844,
    "total_rows_deleted": 0,        // >0 indicates reruns occurred
    "idempotent_reruns_detected": false
  }
}
```

---

### Response Time

| File Size | Features | Typical Time | Chunk Count |
|-----------|----------|--------------|-------------|
| < 10 MB | < 10K | 15-30 sec | 1-10 |
| 10-100 MB | 10K-100K | 30-90 sec | 10-100 |
| 100MB-500MB | 100K-500K | 90-300 sec | 50-250 |
| 500MB-1GB | 500K-2M | 300-600 sec | 250-1000 |
| > 1 GB | > 2M | 600-1200 sec | 1000+ |

**Note**: With 32 parallel workers (4 processes × 8 concurrent), chunk upload speed scales linearly with worker count.

---

### Result Data

Successful completion includes:
```json
{
  "status": "completed",
  "resultData": {
    "job_type": "process_vector",
    "blob_name": "acled_export.csv",
    "file_extension": "csv",
    "table_name": "acled_events",
    "schema": "geo",
    "summary": {
      "total_chunks": 129,
      "chunks_uploaded": 129,
      "chunks_failed": 0,
      "total_rows_inserted": 2570844,
      "total_rows_deleted": 0,
      "idempotent_reruns_detected": false,
      "success_rate": "100.0%",
      "data_complete": true
    },
    "stac": {
      "collection_id": "system-vectors",
      "stac_id": "acled_events",
      "inserted_to_pgstac": true,
      "feature_count": 2570844,
      "bbox": [-180.0, -56.0, 180.0, 85.0]
    },
    "ogc_features_url": "https://rmhazuregeoapi-.../api/features/collections/acled_events",
    "viewer_url": "https://rmhazuregeoapi-.../api/vector/viewer?collection=acled_events",
    "stages_completed": 3,
    "total_tasks_executed": 131,
    "tasks_by_status": {
      "completed": 131,
      "failed": 0
    }
  }
}
```

---

### Supported File Formats

| Format | Extension | Converter Params | Notes |
|--------|-----------|------------------|-------|
| CSV | `.csv` | `lat_name`, `lon_name` OR `wkt_column` | **Required** geometry column params |
| GeoJSON | `.geojson`, `.json` | None | Direct load, best performance |
| GeoPackage | `.gpkg` | `layer_name` (optional) | SQLite-based, multi-layer support |
| KML | `.kml` | None | Google Earth format |
| KMZ | `.kmz` | `kml_name` (optional) | Zipped KML |
| Shapefile | `.shp`, `.zip` | `shp_name` (optional) | Zipped shapefile components |

---

### Common Issues

**1. CSV missing converter_params**:
```json
{
  "error": "CSV conversion requires either 'wkt_column' or both 'lat_name' and 'lon_name'"
}
```
**Solution**: Add `converter_params` with `lat_name`/`lon_name` or `wkt_column`

**2. Wrong CSV column names**:
```json
{
  "error": "ValueError: lat_name 'latitude' not found in columns"
}
```
**Solution**: Check exact column names in your CSV (case-sensitive)

**3. File not found**:
```json
{
  "error": "Blob 'data.csv' does not exist in container 'rmhazuregeobronze'"
}
```
**Solution**: Verify file exists in container using Azure Portal or CLI

**4. Invalid geometry**:
```json
{
  "error": "GEOSException: Invalid geometry"
}
```
**Solution**: Clean geometry using QGIS "Fix geometries" or similar

**5. GeoPackage layer not found**:
```json
{
  "error": "Layer 'my_layer' not found in GeoPackage"
}
```
**Solution**: Check available layers, or omit `layer_name` to use first layer

---

### Access Ingested Data

**OGC Features API** (standards-compliant GeoJSON):
```bash
# Collection metadata
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/features/collections/{table_name}

# Query features (with pagination)
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/features/collections/{table_name}/items?limit=100&offset=0"

# Spatial query (bounding box)
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/features/collections/{table_name}/items?bbox=-70.7,-56.3,-70.6,-56.2"

# Single feature by ID
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/features/collections/{table_name}/items/1
```

**Vector Viewer** (interactive Leaflet map):
```
https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/vector/viewer?collection={table_name}
```

---

## 3. Process Raster Job

**Purpose**: Convert raster files (GeoTIFF, etc.) to Cloud-Optimized GeoTIFF (COG) with STAC metadata

**Job Type**: `process_raster`

---

### CoreMachine API (Direct)

Direct submission when you know the exact output folder and collection names.

#### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `blob_name` | string | **Yes** | - | Name of raster file in blob storage (e.g., "image.tif") |
| `container_name` | string | **Yes** | - | Source blob container (e.g., "rmhazuregeobronze") |
| `collection_id` | string | No | "system-rasters" | STAC collection ID for metadata |
| `item_id` | string | No | Auto-generated | Custom STAC item ID |
| `raster_type` | string | No | "auto" | Raster type detection mode |
| `output_tier` | string | No | "analysis" | COG compression tier |
| `target_crs` | string | No | "EPSG:4326" | Target coordinate reference system |
| `input_crs` | string | No | null | Source CRS (if not in file metadata) |
| `jpeg_quality` | int | No | 85 | JPEG quality for visualization tier (1-100) |
| `strict_mode` | bool | No | false | Fail on warnings (not just errors) |
| `output_folder` | string | No | null | Custom output folder in silver container |

#### Raster Types

| Type | Description | Compression |
|------|-------------|-------------|
| `auto` | Auto-detect from band count, dtype, color interpretation | Varies |
| `rgb` | 3-band RGB imagery | JPEG |
| `rgba` | 4-band RGBA imagery | JPEG (RGB) + LZW (Alpha) |
| `dem` | Digital Elevation Model (single band float) | DEFLATE |
| `categorical` | Classified/categorical raster | LZW |
| `multispectral` | Multi-band scientific data | DEFLATE |
| `nir` | Near-infrared imagery | DEFLATE |

#### Output Tiers

| Tier | Compression | Access Tier | Use Case | Status |
|------|-------------|-------------|----------|--------|
| `visualization` | JPEG (Q85) | Hot | Web display, TiTiler, fast streaming | ⚠️ BROKEN |
| `analysis` | DEFLATE | Hot | Scientific analysis, lossless | ✅ **RECOMMENDED** |
| `archive` | LZW | Cool | Long-term storage, cost-optimized | ✅ Works |
| `all` | All above | Mixed | Create all applicable tiers | ⚠️ Partial |

**⚠️ KNOWN ISSUE (21 NOV 2025)**: `visualization` tier (JPEG compression) is currently failing with `COG_TRANSLATE_FAILED`. Use `analysis` tier (DEFLATE) as workaround. See [TODO.md](docs_claude/TODO.md) for investigation status.

#### Size Limits (13 DEC 2025)

| Limit | Value | Behavior |
|-------|-------|----------|
| **Max file size** | 800 MB | Files >800MB rejected with error directing to `process_large_raster_v2` |
| **Min file size** | None | Any size accepted (but very small files process faster) |

**Pre-flight validation** automatically checks file size before processing. Large files are rejected immediately with a clear error message.

#### CoreMachine Examples

**Working example** (13 DEC 2025 - verified with dctest.tif, 25.8 MB):
```bash
curl -X POST \
  https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/process_raster_v2 \
  -H 'Content-Type: application/json' \
  -d '{
    "blob_name": "dctest.tif",
    "container_name": "rmhazuregeobronze"
  }'
```

**Response** (job created successfully):
```json
{
  "job_id": "3dadb0696eb5bf763b7e784864d456aed8eaafe4e02012f33cca747f52e541ab",
  "status": "created",
  "parameters": {
    "blob_name": "dctest.tif",
    "container_name": "rmhazuregeobronze",
    "_blob_size_mb": 25.82,
    "_blob_size_bytes": 27077396
  }
}
```

**Results**:
| Metric | Value |
|--------|-------|
| Status | `completed` |
| File Size | 25.82 MB |
| Processing Time | ~22 seconds total |
| COG Size | 127.58 MB (DEFLATE compression) |
| STAC Inserted | Yes |
| TiTiler URLs | Generated (9 URLs including viewer, preview, tilejson)

**Large file rejection example** (13 DEC 2025 - antigua.tif, 11.16 GB):
```bash
curl -X POST \
  https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/process_raster_v2 \
  -H 'Content-Type: application/json' \
  -d '{
    "blob_name": "antigua.tif",
    "container_name": "rmhazuregeobronze"
  }'
```

**Response** (rejected - file too large):
```json
{
  "error": "Bad request",
  "message": "Pre-flight validation failed: Raster file too_large for direct processing. Use process_large_raster_v2 for files over size limit."
}
```

**Solution**: Use `process_large_raster_v2` for files >800 MB (supports 100 MB - 30 GB)

**Basic raster to COG (uses defaults)**:
```bash
curl -X POST \
  https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/process_raster \
  -H 'Content-Type: application/json' \
  -d '{
    "blob_name": "dctest.tif",
    "container_name": "rmhazuregeobronze"
  }'
```

**With specific collection (for organized STAC catalog)**:
```bash
curl -X POST \
  https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/process_raster \
  -H 'Content-Type: application/json' \
  -d '{
    "blob_name": "satellite_image.tif",
    "container_name": "rmhazuregeobronze",
    "collection_id": "satellite-imagery-2025",
    "raster_type": "rgb",
    "output_tier": "visualization"
  }'
```

**DEM processing (elevation data)**:
```bash
curl -X POST \
  https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/process_raster \
  -H 'Content-Type: application/json' \
  -d '{
    "blob_name": "elevation.tif",
    "container_name": "rmhazuregeobronze",
    "collection_id": "terrain-data",
    "raster_type": "dem",
    "output_tier": "analysis"
  }'
```

**Reproject to Web Mercator**:
```bash
curl -X POST \
  https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/process_raster \
  -H 'Content-Type: application/json' \
  -d '{
    "blob_name": "map_image.tif",
    "container_name": "rmhazuregeobronze",
    "target_crs": "EPSG:3857",
    "output_tier": "visualization"
  }'
```

**High-quality visualization COG**:
```bash
curl -X POST \
  https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/process_raster \
  -H 'Content-Type: application/json' \
  -d '{
    "blob_name": "aerial_photo.tif",
    "container_name": "rmhazuregeobronze",
    "output_tier": "visualization",
    "jpeg_quality": 95
  }'
```

### Workflow Stages

**Stage 1**: Validate Raster (single task)
- Download and analyze raster metadata
- Detect raster type (RGB, DEM, categorical, etc.)
- Check CRS and bounds
- Validate band structure
- Duration: 2-10 seconds

**Stage 2**: Create COG (single task)
- Download full raster
- Reproject if needed
- Convert to Cloud-Optimized GeoTIFF
- Apply compression based on tier
- Upload to silver-cogs container
- Duration: 10-300 seconds (depends on size)

**Stage 3**: Create STAC Metadata (single task)
- Generate STAC item metadata
- Insert into pgSTAC catalog
- Register with TiTiler
- Generate visualization URLs
- Duration: 2-5 seconds

### Response Time

| File Size | Typical Time | Notes |
|-----------|--------------|-------|
| < 10 MB | 15-30 sec | Small images |
| 10-50 MB | 30-60 sec | Medium imagery |
| 50-200 MB | 60-180 sec | Large rasters |
| > 200 MB | Use `process_large_raster` instead | Tiled processing |

### Result Data

**Real example** (21 NOV 2025 - dctest.tif 27 MB RGB GeoTIFF):
```json
{
  "status": "completed",
  "resultData": {
    "job_type": "process_raster",
    "source_blob": "dctest.tif",
    "source_container": "rmhazuregeobronze",
    "validation": {
      "warnings": [],
      "confidence": "VERY_HIGH",
      "source_crs": "EPSG:4326",
      "raster_type": "rgb",
      "bit_depth_efficient": true
    },
    "cog": {
      "size_mb": 127.58,
      "cog_blob": "cogs/dctest_titiler_test/dctest_cog_analysis.tif",
      "compression": "deflate",
      "cog_container": "silver-cogs",
      "reprojection_performed": false,
      "processing_time_seconds": 9.91
    },
    "stac": {
      "bbox": [-77.028, 38.908, -77.013, 38.932],
      "item_id": "system-rasters-cogs-dctest_titiler_test-dctest_cog_analysis-tif",
      "collection_id": "system-rasters",
      "ready_for_titiler": true,
      "inserted_to_pgstac": true
    },
    "share_url": "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/WebMercatorQuad/map.html?url=%2Fvsiaz%2Fsilver-cogs%2Fcogs%2Fdctest_titiler_test%2Fdctest_cog_analysis.tif",
    "titiler_urls": {
      "viewer_url": "https://rmhtitiler-.../cog/WebMercatorQuad/map.html?url=...",
      "info_url": "https://rmhtitiler-.../cog/info?url=...",
      "preview_url": "https://rmhtitiler-.../cog/preview.png?url=...&max_size=512",
      "thumbnail_url": "https://rmhtitiler-.../cog/preview.png?url=...&max_size=256",
      "tilejson_url": "https://rmhtitiler-.../cog/WebMercatorQuad/tilejson.json?url=...",
      "statistics_url": "https://rmhtitiler-.../cog/statistics?url=...",
      "bounds_url": "https://rmhtitiler-.../cog/bounds?url=...",
      "tiles_url_template": "https://rmhtitiler-.../cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png?url=..."
    },
    "stages_completed": 3,
    "total_tasks_executed": 3,
    "tasks_by_status": {
      "completed": 3,
      "failed": 0
    }
  }
}
```

**Key URLs in result:**
- `share_url` - **PRIMARY** - Direct link to interactive TiTiler map viewer (share this URL with users)
- `titiler_urls.viewer_url` - Same as share_url
- `titiler_urls.preview_url` - PNG thumbnail (512px)
- `titiler_urls.tilejson_url` - TileJSON spec for web maps (Leaflet, MapLibre, etc.)

### Access Processed Rasters

**STAC API** (metadata search):
```bash
# List collections
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/collections

# Get items in collection
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/collections/system-rasters/items
```

**TiTiler** (tile serving):
- Preview: `https://titiler.../preview.png?collection={id}&item={item_id}`
- Tiles: `https://titiler.../tiles/{z}/{x}/{y}.png?collection={id}&item={item_id}`
- TileJSON: `https://titiler.../tilejson.json?collection={id}&item={item_id}`

**Direct COG Access**:
```
azure://silver-cogs/{blob_name}_cog.tif
```

### Common Issues

**1. CRS_CHECK_FAILED**:
```json
{
  "status": "failed",
  "error_details": "CRS_CHECK_FAILED"
}
```
**Solution**: Specify `input_crs` parameter if CRS is missing from file metadata

**2. File too large**:
```json
{
  "status": "failed",
  "error_details": "File exceeds size limit for process_raster"
}
```
**Solution**: Use `process_large_raster` job for files > 200 MB

**3. Unsupported format**:
```json
{
  "status": "failed",
  "error_details": "Cannot open raster file"
}
```
**Solution**: Convert to GeoTIFF first, ensure GDAL can read the format

**4. COG_TRANSLATE_FAILED (JPEG compression)**:
```json
{
  "status": "failed",
  "error_details": "COG_TRANSLATE_FAILED"
}
```
**Solution**: Use `output_tier: "analysis"` (DEFLATE) instead of `visualization` (JPEG). This is a known issue with JPEG compression in Azure Functions. See [TODO.md](docs_claude/TODO.md) for investigation.

**5. STAC insertion failed** (COG created but metadata failed):
```json
{
  "status": "completed_with_errors",
  "message": "COG created but STAC insertion failed",
  "cog_path": "silver-cogs/file_cog.tif"
}
```
**Solution**: COG is usable, manually add to STAC if needed

---

### Platform API (DDH Integration)

<!-- TODO: Add Platform API examples after testing (22 NOV 2025)

     Platform API uses DDH identifiers instead of CoreMachine parameters:
     - dataset_id, resource_id, version_id → auto-generated output folders and STAC IDs
     - Endpoint: POST /api/platform/request
     - Status: GET /api/platform/status/{request_id}

     Example structure (to be tested and verified):
     {
       "dataset_id": "aerial-imagery",
       "resource_id": "site-alpha",
       "version_id": "v1-0",
       "data_type": "raster",
       "file_name": "image.tif",
       "container_name": "bronze-rasters",
       "service_name": "DDH Raster Import",
       "description": "Aerial imagery for Site Alpha",
       "tags": ["aerial", "rgb"],
       "access_level": "public",
       "options": {
         "output_tier": "analysis",
         "target_crs": "EPSG:4326"
       }
     }

     Output:
     - Output folder: aerial-imagery/site-alpha/v1-0 (auto-generated)
     - Collection ID: aerial-imagery (auto-generated)
     - STAC item ID: aerial-imagery_site-alpha_v1-0 (auto-generated)
     - TiTiler viewer URL: auto-generated with search_id
-->

---

### Supported Input Formats

| Format | Extension | Notes |
|--------|-----------|-------|
| GeoTIFF | `.tif`, `.tiff` | Preferred format |
| BigTIFF | `.tif` | For files > 4 GB |
| JPEG 2000 | `.jp2` | Slower processing |
| PNG | `.png` | Must be georeferenced |
| ERDAS IMAGINE | `.img` | Legacy format |
| NetCDF | `.nc` | Scientific data |

### Use Cases
- Convert satellite imagery to web-optimized COG
- Process aerial photography for visualization
- Create analysis-ready DEMs
- Reproject rasters to standard CRS
- Catalog rasters with STAC metadata
- Enable TiTiler tile serving
- Archive large raster collections

---

## 4. Process Raster Collection Job

**Purpose**: Process multiple raster files into a unified STAC collection with MosaicJSON for seamless tile serving

**Job Type**: `process_raster_collection`

---

### CoreMachine API (Direct)

Direct submission when you know the exact blob paths and collection names.

#### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `container_name` | string | **Yes** | - | Source blob container (e.g., "rmhazuregeobronze") |
| `blob_list` | list | **Yes** | - | List of raster blob paths to process |
| `collection_id` | string | No | Auto-generated | STAC collection identifier |
| `output_folder` | string | No | Auto-generated | Output folder in silver-cogs container |
| `target_crs` | string | No | "EPSG:4326" | Target coordinate reference system |
| `output_tier` | string | No | "analysis" | COG compression tier |
| `jpeg_quality` | int | No | 85 | JPEG quality (1-100) |
| `create_mosaicjson` | bool | No | true | Create MosaicJSON index |
| `create_stac_collection` | bool | No | true | Create STAC collection |

#### Size and Count Limits (13 DEC 2025)

| Limit | Value | Behavior |
|-------|-------|----------|
| **Max files per collection** | 20 | Collections with >20 files rejected at pre-flight |
| **Max individual file size** | 800 MB | Collections containing ANY file >800MB rejected |
| **Min files per collection** | 2 | Single files should use `process_raster_v2` |

**Pre-flight validation** checks:
1. **Collection count** - Rejected immediately if >20 files (before any blob API calls)
2. **Individual file sizes** - Each blob is checked in parallel; rejected if ANY exceeds 800MB
3. **File existence** - All blobs must exist in the container

**Why these limits?**
- Collections with >20 files should be submitted in smaller batches for efficiency
- Large rasters (>800MB) require Docker worker processing (coming soon)
- Current Azure Functions have memory/timeout constraints for large raster operations

**Size metadata captured** (available in job parameters after validation):
```json
{
  "_blob_list_count": 4,
  "_blob_list_max_size_mb": 777.69,
  "_blob_list_total_size_mb": 1619.37,
  "_blob_list_largest_blob": "namangan/namangan14aug2019_R1C1cog.tif",
  "_blob_list_has_large_raster": false
}
```

#### CoreMachine Examples

**Working example** (13 DEC 2025 - verified with Namangan imagery, 4 tiles, 1.6 GB total):
```bash
curl -X POST \
  https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/process_raster_collection_v2 \
  -H 'Content-Type: application/json' \
  -d '{
    "container_name": "rmhazuregeobronze",
    "blob_list": [
      "namangan/namangan14aug2019_R1C1cog.tif",
      "namangan/namangan14aug2019_R1C2cog.tif",
      "namangan/namangan14aug2019_R2C1cog.tif",
      "namangan/namangan14aug2019_R2C2cog.tif"
    ],
    "collection_id": "namangan-test"
  }'
```

**Response** (job created with size metadata):
```json
{
  "job_id": "1574336e5362c6acc1301f6f275bcab3a7922cde381d75d44bd0e3f586257547",
  "status": "created",
  "parameters": {
    "blob_list": ["namangan/namangan14aug2019_R1C1cog.tif", "..."],
    "_blob_list_count": 4,
    "_blob_list_max_size_mb": 777.69,
    "_blob_list_total_size_mb": 1619.37,
    "_blob_list_largest_blob": "namangan/namangan14aug2019_R1C1cog.tif",
    "_blob_list_has_large_raster": false
  }
}
```

**Results** (Namangan 4-tile collection - 1.6 GB total):
| Metric | Value |
|--------|-------|
| Status | `completed` |
| Files | 4 (778 MB, 704 MB, 73 MB, 65 MB) |
| Total Size | 1,619 MB |
| Largest File | 777.69 MB (under 800 MB limit) |
| Total Tasks | 10 (4 COG + 4 STAC items + MosaicJSON + Collection) |
| Duration | ~9 minutes |
| Bounding Box | `[71.6063, 40.9806, 71.7219, 41.0318]` (Namangan, Uzbekistan) |

**Collection count rejection example** (13 DEC 2025 - 21 files):
```bash
curl -X POST \
  https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/process_raster_collection_v2 \
  -H 'Content-Type: application/json' \
  -d '{
    "container_name": "rmhazuregeobronze",
    "blob_list": ["f1.tif","f2.tif","f3.tif","f4.tif","f5.tif","f6.tif","f7.tif","f8.tif","f9.tif","f10.tif","f11.tif","f12.tif","f13.tif","f14.tif","f15.tif","f16.tif","f17.tif","f18.tif","f19.tif","f20.tif","f21.tif"],
    "collection_id": "test-too-many"
  }'
```

**Response** (rejected - too many files):
```json
{
  "error": "Bad request",
  "message": "Pre-flight validation failed: Collection exceeds maximum file count (20 files). Submit smaller batches or contact support for bulk processing."
}
```

**Solution**: Split collection into batches of ≤20 files each

### Workflow Stages

**Stage 1**: Validate Rasters (parallel tasks)
- Validate each raster file
- Check CRS, bounds, band structure
- Duration: 2-10 seconds per file

**Stage 2**: Create COGs (parallel tasks)
- Convert each raster to COG
- Apply compression
- Upload to silver-cogs
- Duration: 10-300 seconds per file (depends on size)

**Stage 3**: Create MosaicJSON (single task)
- Generate MosaicJSON index from all COGs
- Upload to silver-cogs container (alongside COGs)
- Duration: 2-5 seconds

**Stage 4**: Create STAC Collection (single task)
- Create STAC collection with unified bbox
- Create STAC items for each COG
- Register pgSTAC search with collection bbox
- Generate TiTiler visualization URLs
- Duration: 5-15 seconds

### Result Data

**Real example** (22 NOV 2025 - Namangan 4-tile collection):
```json
{
  "status": "completed",
  "resultData": {
    "job_type": "process_raster_collection",
    "collection_id": "namangan-full-collection",
    "cogs": {
      "successful": 4,
      "failed": 0,
      "total_size_mb": 1654.49
    },
    "stac": {
      "collection_id": "namangan-full-collection",
      "items_created": 4,
      "search_id": "19f27606ef42aaa1ec1fc49878f52ee4",
      "inserted_to_pgstac": true,
      "ready_for_titiler": true
    },
    "mosaicjson": {
      "url": "https://rmhazuregeo.blob.core.windows.net/silver-cogs/namangan_full/namangan-full-collection.json",
      "bounds": [71.6063, 40.9806, 71.7219, 41.0318],
      "tile_count": 4
    },
    "share_url": "https://rmhtitiler-.../searches/{search_id}/WebMercatorQuad/map.html?assets=data",
    "titiler_urls": {
      "viewer_url": "https://rmhtitiler-.../searches/{search_id}/WebMercatorQuad/map.html?assets=data",
      "tilejson_url": "https://rmhtitiler-.../searches/{search_id}/WebMercatorQuad/tilejson.json?assets=data",
      "tiles_url": "https://rmhtitiler-.../searches/{search_id}/tiles/WebMercatorQuad/{z}/{x}/{y}?assets=data"
    },
    "stages_completed": 4,
    "total_tasks_executed": 10,
    "tasks_by_status": {
      "completed": 10,
      "failed": 0
    }
  }
}
```

### Key URLs in Result

- `share_url` - **PRIMARY** - Interactive map viewer (automatically zooms to collection bbox)
- `titiler_urls.viewer_url` - Same as share_url
- `titiler_urls.tilejson_url` - TileJSON spec for web maps
- `titiler_urls.tiles_url` - XYZ tile URL template

### Auto-Zoom Feature (22 NOV 2025)

**The viewer URL now automatically zooms to the collection bounding box.**

When you open the `share_url`, the map automatically zooms to the collection extent instead of showing the entire world. This behavior is achieved by:

1. Collection bbox is extracted from the STAC collection extent
2. Bbox is stored in pgSTAC search metadata as `bounds`
3. TiTiler reads bounds from search metadata when generating TileJSON
4. Leaflet's `map.fitBounds()` uses these bounds for initial view

**Before**: Viewer opened at world zoom level (user had to manually zoom/pan)
**After**: Viewer opens zoomed directly to the data extent (for example, Namangan, Uzbekistan)

---

### Platform API (DDH Integration)

<!-- TODO: Add Platform API examples after testing (22 NOV 2025)

     Platform API uses DDH identifiers instead of CoreMachine parameters:
     - dataset_id, resource_id, version_id → auto-generated collection ID and output folder
     - Endpoint: POST /api/platform/request
     - Status: GET /api/platform/status/{request_id}

     Example structure (to be tested and verified):
     {
       "dataset_id": "satellite-imagery",
       "resource_id": "region-alpha",
       "version_id": "v1-0",
       "data_type": "raster_collection",
       "file_list": [
         "satellite/tile1.tif",
         "satellite/tile2.tif",
         "satellite/tile3.tif"
       ],
       "container_name": "bronze-rasters",
       "service_name": "DDH Satellite Import",
       "description": "Multi-tile satellite collection for Region Alpha",
       "tags": ["satellite", "multispectral"],
       "access_level": "public",
       "options": {
         "output_tier": "analysis",
         "target_crs": "EPSG:4326",
         "create_mosaicjson": true
       }
     }

     Output:
     - Collection ID: satellite-imagery (auto-generated from dataset_id)
     - Output folder: satellite-imagery/region-alpha/v1-0 (auto-generated)
     - MosaicJSON: satellite-imagery/region-alpha/v1-0/collection.json
     - TiTiler viewer URL: auto-generated with auto-zoom to collection bbox
-->

---

### Use Cases

- Process satellite image tile grids (for example, Maxar WorldView)
- Create unified collections from multi-scene acquisitions
- Build seamless mosaics from adjacent raster tiles
- Generate STAC collections with MosaicJSON for dynamic tiling
- Enable TiTiler-PgSTAC search-based tile serving

---

## Monitoring Jobs

### CoreMachine API - Direct Job Monitoring

**Get All Jobs (Last 24 Hours)**:
```bash
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/jobs?limit=100"
```

**Get Tasks for Specific Job**:
```bash
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/tasks/{JOB_ID}"
```

**Filter Jobs by Status**:
```bash
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/jobs?status=failed&limit=20"
```

**Filter Jobs by Type**:
```bash
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/jobs?job_type=process_vector&limit=20"
```

---

### Platform API - Request Status Monitoring

<!-- TODO: Add Platform API status examples after testing (22 NOV 2025)

     Platform status endpoint queries by request_id (DDH identifier hash):
     - Endpoint: GET /api/platform/status/{request_id}
     - Lists all requests: GET /api/platform/status?limit=100
     - Filter by dataset: GET /api/platform/status?dataset_id=aerial-imagery

     Example response structure (to be verified):
     {
       "success": true,
       "request_id": "a3f2c1b8...",
       "dataset_id": "aerial-imagery",
       "resource_id": "site-alpha",
       "version_id": "v1-0",
       "job_id": "abc123...",
       "job_status": "completed",
       "job_result": {...},
       "data_access": {
         "ogc_features": "...",
         "stac": "...",
         "titiler": "..."
       }
     }
-->

---

## 📊 Database Statistics

```bash
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/stats
```

**Response**:
```json
{
  "jobs": {
    "total": 150,
    "by_status": {
      "completed": 142,
      "failed": 5,
      "processing": 3
    }
  },
  "tasks": {
    "total": 1250,
    "by_status": {
      "completed": 1230,
      "failed": 10,
      "processing": 10
    }
  }
}
```

---

## ADMIN AND MAINTENANCE ENDPOINTS (DEV/TEST ONLY)

**WARNING: THESE ARE DESTRUCTIVE OPERATIONS - DEV/TEST ENVIRONMENTS ONLY**

These endpoints perform **DESTRUCTIVE OPERATIONS** that can delete data, drop schemas, and reset the entire system. They are designed for development and testing environments where you need to quickly reset state.

**DO NOT USE IN PRODUCTION** unless you have verified:
- Full database backups
- Explicit approval from data owners
- Maintenance window scheduled
- Users notified of downtime

---

### Database Schema Management

#### 1. Redeploy Schema (Nuclear Option)

**What it does**: Drops ALL tables, functions, enums, and recreates from scratch

```bash
curl -X POST \
  "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/maintenance/redeploy?confirm=yes"
```

**⚠️ DESTROYS**:
- All jobs records (app.jobs)
- All tasks records (app.tasks)
- All orchestration jobs (app.orchestration_jobs)
- All API requests (app.api_requests)
- All PostgreSQL functions (complete_task_and_check_stage, etc.)
- All enums (job_status, task_status, etc.)

**✅ Preserves**:
- PostGIS data in `geo` schema (your vector tables)
- pgSTAC data in `pgstac` schema (STAC collections/items)
- H3 grid data in `h3` schema

**Use when**:
- After major schema changes in code
- Database is in inconsistent state
- Testing fresh deployments
- Development environment reset

**Example response**:
```json
{
  "operation": "schema_redeploy",
  "steps": [
    {
      "step": "nuke_schema",
      "objects_dropped": 13
    },
    {
      "step": "deploy_schema",
      "objects_created": {
        "statements_executed": 38,
        "tables_created": 4,
        "functions_created": 5
      }
    }
  ],
  "overall_status": "success"
}
```

---

#### 2. Nuke Schema Only (Super Nuclear Option)

**What it does**: Drops ALL app schema objects WITHOUT recreating them

```bash
curl -X POST \
  "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/maintenance/nuke?confirm=yes"
```

**⚠️ DESTROYS**: Everything in app schema (jobs, tasks, functions, enums)

**Use when**: You want to manually recreate schema or test fresh installation

**Safer alternative**: Use `redeploy` instead (nukes + recreates in one operation)

---

#### 3. Cleanup Old Records (Safer Option)

**What it does**: Deletes completed/failed jobs older than N days

```bash
curl -X POST \
  "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/maintenance/cleanup?confirm=yes&days=30"
```

**Parameters**:
- `days`: Keep only records from last N days (default: 30)
- `confirm=yes`: Required for safety

**⚠️ Deletes**:
- Completed jobs older than N days
- Failed jobs older than N days
- Associated tasks (CASCADE delete)

**✅ Preserves**:
- Jobs in `queued` or `processing` state
- All data in geo/pgstac/h3 schemas

**Use when**:
- Database is getting large with old job records
- Need to free up space
- Regular maintenance cleanup

**Example**:
```bash
# Delete jobs older than 90 days
curl -X POST \
  "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/maintenance/cleanup?confirm=yes&days=90"
```

---

### STAC Schema Management

#### 4. Install/Reinstall pgSTAC

**What it does**: Installs pgSTAC v0.9.8 schema

```bash
# Fresh install (safe if already installed)
curl -X POST \
  "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/stac/setup?confirm=yes"
```

**Idempotent**: Safe to run multiple times, won't reinstall if already present

**Creates**:
- pgstac schema
- 22 STAC tables (collections, items, searches, etc.)
- 3 roles (pgstac_admin, pgstac_read, pgstac_ingest)

**Response**:
```json
{
  "success": true,
  "version": "0.9.8",
  "tables_created": 22,
  "roles_created": ["pgstac_admin", "pgstac_read", "pgstac_ingest"]
}
```

---

#### 5. Nuke STAC Data (EXTREME CAUTION!)

**What it does**: Deletes ALL STAC collections and items

```bash
# Delete all STAC items and collections
curl -X POST \
  "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/stac/nuke?confirm=yes&mode=all"
```

**Modes**:
- `mode=all` - Delete collections AND items
- `mode=items` - Delete only items (keep collections)
- `mode=collections` - Delete collections (CASCADE deletes items)

**⚠️ DESTROYS**:
- All STAC collections metadata
- All STAC items (raster/vector metadata)
- Search indexes

**✅ Preserves**:
- pgSTAC schema structure (tables, functions remain)
- Actual data in geo schema (PostGIS tables)
- Actual COG files in blob storage (silver-cogs container)

**Use when**:
- Testing STAC workflows from scratch
- Fixing broken STAC metadata
- Much faster than full schema drop

**Example - Clear only items**:
```bash
curl -X POST \
  "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/stac/nuke?confirm=yes&mode=items"
```

---

### Safety Features

All destructive endpoints require:

1. **Explicit Confirmation**:
   - `confirm=yes` parameter required
   - Returns error without it

2. **POST Only**:
   - GET requests are read-only (safe)
   - Destructive operations require POST

3. **Environment Variable Guards** (for most dangerous operations):
   ```bash
   # Some operations check for additional env var
   PGSTAC_CONFIRM_DROP=true
   ```

4. **Audit Logging**:
   - All operations logged to Application Insights
   - Timestamp, user, operation recorded

---

### Recommended Safe Workflow

**Development Reset**:
```bash
# 1. Check current state
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health

# 2. Cleanup old jobs (safe - only removes old completed/failed)
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/maintenance/cleanup?confirm=yes&days=7"

# 3. If needed, redeploy schema (DESTRUCTIVE)
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/maintenance/redeploy?confirm=yes"

# 4. Reinstall pgSTAC (safe - idempotent)
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/stac/setup?confirm=yes"

# 5. Verify everything is healthy
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health
```

---

### When NOT to Use These Endpoints

**Do Not Use in Production If**:
- Users are actively running jobs
- You have important job history to preserve
- STAC catalog has production metadata
- No recent backups exist
- Multiple teams depend on the data

**Use in Development/Test If**:
- Testing new features
- Database is in broken state
- Need clean slate for testing
- Experimenting with schema changes

---

### Alternative: Targeted Fixes

Instead of nuclear options, consider:

1. **Fix specific job**:
   ```sql
   -- Mark stuck job as failed
   UPDATE app.jobs SET status = 'failed' WHERE job_id = 'xxx';
   ```

2. **Fix specific STAC collection**:
   ```bash
   # Delete one collection
   curl -X DELETE https://rmhazuregeoapi-.../api/collections/{collection_id}
   ```

3. **Restart stuck tasks**:
   ```sql
   -- Reset processing tasks to queued
   UPDATE app.tasks SET status = 'queued' WHERE status = 'processing' AND heartbeat < NOW() - INTERVAL '10 minutes';
   ```

---

## 🧪 Testing Workflow

**1. Health Check**:
```bash
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health
```

**2. Simple Test Job**:
```bash
curl -X POST \
  https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/hello_world \
  -H 'Content-Type: application/json' \
  -d '{"message": "deployment test", "n": 2}'
```

**3. Get Job ID from response**, then check status:
```bash
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}
```

**4. Verify completion** (status should be "completed")

**5. Vector Ingestion Test**:
```bash
curl -X POST \
  https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/process_vector \
  -H 'Content-Type: application/json' \
  -d '{
    "blob_name": "8.geojson",
    "file_extension": "geojson",
    "table_name": "deployment_test_vector"
  }'
```

**6. Check vector job status** and verify OGC Features URL works

---

## 📝 Notes

- **Job IDs**: SHA256 hash of (job_type + parameters) = natural deduplication
- **Idempotency**: Same parameters = same job_id, returns existing job
- **Retries**: Disabled in dev mode (`maxDequeueCount: 1` in host.json)
- **Timeouts**: Function timeout = 30 minutes (configurable)
- **Parallelism**: Service Bus allows 20 concurrent tasks by default
- **Queue Visibility**: Messages invisible for 5 minutes during processing

---

## 🔗 Related Documentation

- **Health Endpoint**: `/api/health` - System status
- **OGC Features API**: `/api/features` - Vector data access
- **STAC API**: `/api/collections` - Metadata catalog
- **Database Admin**: `/api/dbadmin/*` - Database monitoring
- **Architecture**: See `docs_claude/CLAUDE_CONTEXT.md`
- **Configuration**: See `config/` package
- **Job Creation**: See `JOB_CREATION_QUICKSTART.md` for creating new jobs

---

**Last Updated**: 13 DEC 2025
**Function App**: rmhazuregeoapi (B3 Basic tier)
**Region**: East US
**Python Version**: 3.12
