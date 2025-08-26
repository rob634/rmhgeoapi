# API Reference and Quick Commands

## 🚨 IMPORTANT: Endpoint Usage

**Primary Endpoint**: `/api/jobs/{operation_type}`

All operations use the `submit_job` endpoint with the operation type in the URL path.

### Required Parameters
- **DDH Operations** (Data Discovery Hub): Require `dataset_id`, `resource_id`, and `version_id`
- **System Operations** (Internal): Set `system: true` to bypass DDH requirements
- **Without `system: true`**: The API expects DDH parameters and will return an error if missing

## 🛠️ Available Operations

### Container Operations
- `list_container` - List storage contents with comprehensive statistics
- `sync_container` - Sync entire container to STAC catalog

### STAC Operations
- `stac_item_quick` - Quick catalog (metadata only)
- `stac_item_full` - Full extraction (downloads file)
- `stac_item_smart` - Smart extraction (header-only for large rasters)
- `setup_stac_geo_schema` - Initialize STAC tables
- `catalog_file` - Standalone STAC cataloging for any file

### Raster Operations
- `cog_conversion` - Convert to Cloud Optimized GeoTIFF
- `reproject_raster` - Change projection
- `validate_raster` - Check raster validity
- `extract_metadata` - Extract comprehensive metadata
- `simple_cog` - State-managed COG conversion (<4GB files)
- `generate_tiling_plan` - Create PostGIS tiling plan for large rasters
- `tile_raster` - Execute tiling based on existing plan

### Database Metadata Operations (NEW)
- `list_collections` - List all STAC collections with statistics
- `list_items` - Query STAC items with filtering (bbox, datetime, collection)
- `get_database_summary` - Get overall database statistics and summary
- `get_collection_details` - Get detailed metadata for a specific collection
- `export_metadata` - Export database metadata in JSON/GeoJSON/CSV formats
- `query_spatial` - Perform spatial queries on the database
- `get_statistics` - Get statistics grouped by collection/date/file_type/CRS

### Database Operations
- `list_schemas` - Show database schemas
- `describe_table` - Get table structure
- `get_postgis_info` - PostGIS capabilities

## 🎮 Quick Commands

### List Container Contents
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/list_container \
  -H "x-functions-key: [FUNCTION_KEY_REMOVED]" \
  -H "Content-Type: application/json" \
  -d '{"dataset_id":"rmhazuregeobronze","resource_id":"none","version_id":"v1","system":true}'
```

### Sync Entire Container to STAC
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/sync_container \
  -H "Content-Type: application/json" \
  -H "x-functions-key: [FUNCTION_KEY_REMOVED]" \
  -d '{"dataset_id":"rmhazuregeobronze","resource_id":"full_sync","version_id":"bronze-assets"}'
```

### Database Metadata Operations

#### Get Database Summary
```bash
# Get overall database statistics (system operation - no DDH parameters required)
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/get_database_summary \
  -H "Content-Type: application/json" \
  -H "x-functions-key: [FUNCTION_KEY_REMOVED]" \
  -d '{"system": true}'
```

#### List STAC Collections
```bash
# List all collections with statistics
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/list_collections \
  -H "Content-Type: application/json" \
  -H "x-functions-key: [FUNCTION_KEY_REMOVED]" \
  -d '{"system": true, "include_stats": true}'
```

#### Query STAC Items
```bash
# Query items with filtering
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/list_items \
  -H "Content-Type: application/json" \
  -H "x-functions-key: [FUNCTION_KEY_REMOVED]" \
  -d '{
    "system": true,
    "collection_id": "maxar_delivery",
    "limit": 10,
    "bbox": "-180,-90,180,90"
  }'
```

#### Get Collection Details
```bash
# Get detailed metadata for a specific collection
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/get_collection_details \
  -H "Content-Type: application/json" \
  -H "x-functions-key: [FUNCTION_KEY_REMOVED]" \
  -d '{"system": true, "collection_id": "maxar_delivery"}'
```

#### Export Database Metadata
```bash
# Export metadata as JSON (default)
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/export_metadata \
  -H "Content-Type: application/json" \
  -H "x-functions-key: [FUNCTION_KEY_REMOVED]" \
  -d '{"system": true, "format": "json", "include_items": false}'

# Export as GeoJSON for spatial visualization
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/export_metadata \
  -H "Content-Type: application/json" \
  -H "x-functions-key: [FUNCTION_KEY_REMOVED]" \
  -d '{"system": true, "format": "geojson"}'
```

#### Get Statistics by Group
```bash
# Get statistics grouped by file type
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/get_statistics \
  -H "Content-Type: application/json" \
  -H "x-functions-key: [FUNCTION_KEY_REMOVED]" \
  -d '{"system": true, "group_by": "file_type"}'
```

### Check Poison Queues
```bash
# Peek at poison messages
curl -X GET https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/monitor/poison \
  -H "x-functions-key: [FUNCTION_KEY_REMOVED]"

# Process all poison messages
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/monitor/poison \
  -H "Content-Type: application/json" \
  -H "x-functions-key: [FUNCTION_KEY_REMOVED]" \
  -d '{"process_all": true}'
```

### Validate Raster
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/validate_raster \
  -H "Content-Type: application/json" \
  -H "x-functions-key: [FUNCTION_KEY_REMOVED]" \
  -d '{"dataset_id":"rmhazuregeobronze","resource_id":"file.tif","version_id":"v1"}'
```

### Convert to COG
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/cog_conversion \
  -H "Content-Type: application/json" \
  -H "x-functions-key: [FUNCTION_KEY_REMOVED]" \
  -d '{"dataset_id":"rmhazuregeobronze","resource_id":"file.tif","version_id":"v1"}'
```

### Standalone STAC Cataloging
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/catalog_file \
  -H "Content-Type: application/json" \
  -H "x-functions-key: [FUNCTION_KEY_REMOVED]" \
  -d '{"dataset_id":"rmhazuregeosilver","resource_id":"file_cog.tif","version_id":"v1"}'
```

### Submit STAC Cataloging (Smart Mode for Large File)
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/stac_item_smart \
  -H "Content-Type: application/json" \
  -H "x-functions-key: [FUNCTION_KEY_REMOVED]" \
  -d '{"dataset_id":"rmhazuregeobronze","resource_id":"antigua_cog.tif","version_id":"smart"}'
```

### State-Managed COG Conversion
```bash
# Submit a state-managed COG job for simple file
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/simple_cog \
  -H "Content-Type: application/json" \
  -H "x-functions-key: [FUNCTION_KEY_REMOVED]" \
  -d '{"dataset_id":"rmhazuregeobronze","resource_id":"05APR13082706.tif","version_id":"test_v1"}'

# Submit for nested Maxar file
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/simple_cog \
  -H "Content-Type: application/json" \
  -H "x-functions-key: [FUNCTION_KEY_REMOVED]" \
  -d '{"dataset_id":"rmhazuregeobronze","resource_id":"6672805950159176487/200007488011_01/200007488011_01_P001_PSH/25FEB02023857-S2AS-200007488011_01_P001.TIF","version_id":"maxar_test"}'
```

### Check Job Status
```bash
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/{job_id} \
  -H "x-functions-key: [FUNCTION_KEY_REMOVED]"
```

### Run Full STAC Inventory
```bash
python scripts/full_stac_inventory.py  # Processes all files in bronze container
```

## 📊 Container Listing Response Format
The `list_container` operation returns comprehensive JSON:
```json
{
  "summary": {
    "total_files": 83,
    "total_size_mb": 71108.29,
    "file_extensions": {"tif": 19, "geojson": 3, ...},
    "largest_file": {...},
    "newest_file": {...}
  },
  "files": [
    {
      "name": "file.tif",
      "size": bytes,
      "last_modified": "ISO-8601",
      "content_type": "image/tiff",
      "etag": "Azure etag",
      "inferred_metadata": {...}  // See METADATA_INFERENCE.md
    }
  ]
}
```

## Response Formats

### Job Status Response
```json
{
  "job_id": "sha256_hash",
  "status": "completed|processing|failed",
  "progress": 100,
  "tasks": {
    "total": 2,
    "completed": 2,
    "failed": 0,
    "details": [...]
  },
  "result": {...},
  "error": null
}