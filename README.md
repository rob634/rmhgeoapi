# Azure Geospatial ETL Pipeline

Production-ready Azure Functions application for processing geospatial data through Bronze→Silver→Gold tiers with STAC cataloging.

## 🎯 Overview

This is a serverless geospatial ETL pipeline that:
- Processes raster and vector geospatial data
- Implements idempotent job processing via SHA256 hashing
- Provides STAC (SpatioTemporal Asset Catalog) metadata generation
- Supports files up to 20GB using smart header-only access
- Uses PostgreSQL/PostGIS for spatial data storage
- Tracks jobs in Azure Table Storage

## 🏗️ Architecture

```
HTTP API → Queue → Processing Service → Storage/Database
         ↓                             ↓
    Job Tracking                  STAC Catalog
   (Table Storage)               (PostgreSQL/PostGIS)
```

**Pattern**: Controller → Service → Repository with ABC classes for extensibility

## 📁 Project Structure

```
rmhgeoapi/
├── function_app.py          # Azure Functions entry point
├── services.py              # Service layer with ABC base class
├── repositories.py          # Azure Table/Blob Storage operations
├── database_client.py       # PostgreSQL/PostGIS client (psycopg3)
├── database_health.py       # Database health check service
├── stac_service.py          # STAC cataloging service
├── stac_repository.py       # STAC data persistence
├── stac_models.py           # STAC data models
├── models.py                # Core data models
├── config.py                # Configuration management
├── logger_setup.py          # Centralized logging
├── requirements.txt         # Python dependencies
├── host.json               # Azure Functions configuration
└── README.md               # This file
```

## 🚀 Deployment

### Prerequisites

- Azure subscription
- Azure CLI installed
- Python 3.11+ (Azure Functions uses 3.12)
- Azure Functions Core Tools v4

### Environment Setup

```bash
# Install Azure Functions Core Tools
brew tap azure/functions
brew install azure-functions-core-tools@4

# Clone repository
git clone https://github.com/rob634/rmhgeoapi.git
cd rmhgeoapi

# Create Python environment
conda create -n azgeo python=3.12
conda activate azgeo

# Install dependencies
pip install -r requirements.txt
```

### Local Development

```bash
# Set environment variables
export STORAGE_ACCOUNT_NAME="rmhazuregeo"
export POSTGIS_HOST="your-postgres-host"
export POSTGIS_DATABASE="your-database"
export POSTGIS_USER="your-user"
export POSTGIS_PASSWORD="your-password"
export POSTGIS_PORT="5432"
export POSTGIS_SCHEMA="geo"

# Start locally
func start
```

### Deploy to Azure

```bash
# Login to Azure
az login

# Deploy to Function App
func azure functionapp publish <function-app-name> --python
```

### Important: Avoid Naming Conflicts

⚠️ **Critical**: Do not create folders with the same names as Python files. This causes import conflicts and prevents Azure Functions from registering properly.

## 📋 API Endpoints

### Health Check
```bash
GET /api/health
```

### Submit Job
```bash
POST /api/jobs/{operation_type}
Content-Type: application/json
x-functions-key: <your-function-key>

{
  "dataset_id": "rmhazuregeobronze",
  "resource_id": "file.tif",
  "version_id": "v1"
}
```

### Check Job Status
```bash
GET /api/jobs/{job_id}
x-functions-key: <your-function-key>
```

### Database Health Check
```bash
POST /api/jobs/database_health
Content-Type: application/json
x-functions-key: <your-function-key>

{
  "dataset_id": "health",
  "resource_id": "check",
  "version_id": "v1",
  "system": true
}
```

## 🛠️ Available Operations

### Container Operations
- `list_container` - List storage container contents with statistics

### Database Operations
- `database_health` - Check PostgreSQL/PostGIS connectivity

### STAC Operations
- `stac_item_quick` - Quick catalog (metadata only)
- `stac_item_full` - Full extraction (downloads file)
- `stac_item_smart` - Smart extraction (header-only for large rasters)
- `setup_stac_geo_schema` - Initialize STAC tables
- `sync_container` - Sync entire container to STAC

### Future Operations
- `cog_conversion` - Convert to Cloud Optimized GeoTIFF
- `reproject_raster` - Change projection
- `validate_raster` - Check raster validity
- `extract_metadata` - Extract comprehensive metadata

## 🔑 Key Features

### Job Idempotency
Jobs are identified by SHA256 hash of parameters:
```
{operation_type}:{dataset_id}:{resource_id}:{version_id}
```
Same parameters always produce the same job ID, preventing duplicate processing.

### Smart Mode for Large Files
- Processes files up to 20GB without downloading
- Uses direct URL access via SAS tokens
- Reads raster headers only
- Extracts: bbox, CRS, dimensions, bands, compression

### Centralized Logging
- Unified logging system across all modules
- Buffered logging for performance
- Automatic log flushing on errors
- Structured logging for Azure Monitor

## 🔍 Troubleshooting

### Functions Not Appearing in Azure Portal

**Problem**: Functions deployed but not visible in Azure Portal

**Solution**: Check for folder/file naming conflicts. Ensure no folders have the same names as .py files.

### Queue Messages Going to Poison Queue

**Problem**: Jobs failing and moving to poison queue

**Solutions**:
1. Check environment variables are set correctly
2. Verify database connectivity
3. Check Azure Function logs for exceptions
4. Ensure storage account permissions

### Database Connection Issues

**Problem**: Database health check failing

**Solutions**:
1. Verify PostgreSQL credentials
2. Check firewall rules allow Azure Functions IP
3. Ensure PostGIS extension is installed
4. Verify schema exists

## 📊 Configuration

### Required Environment Variables

```bash
# Storage (usually auto-configured by Azure Functions)
AzureWebJobsStorage=<connection-string>

# PostgreSQL/PostGIS
POSTGIS_HOST=<your-host>
POSTGIS_DATABASE=<your-database>
POSTGIS_USER=<your-user>
POSTGIS_PASSWORD=<your-password>
POSTGIS_PORT=5432
POSTGIS_SCHEMA=geo

# Optional
STORAGE_ACCOUNT_NAME=<storage-account>
```

### Azure Function App Settings

For managed identity with queue triggers:
```
Storage__queueServiceUri = https://<storage>.queue.core.windows.net
Storage__serviceUri = https://<storage>.queue.core.windows.net
```

## 🧪 Testing

### Test Idempotency
```python
# Submit same job twice - should get same job_id
curl -X POST .../api/jobs/list_container -d '{"dataset_id":"test",...}'
curl -X POST .../api/jobs/list_container -d '{"dataset_id":"test",...}'
```

### Test Database Health
```bash
# Should return health status with PostgreSQL/PostGIS info
curl -X POST .../api/jobs/database_health \
  -H "x-functions-key: <key>" \
  -d '{"dataset_id":"health","resource_id":"check","version_id":"v1"}'
```

## 📈 Performance

- **Quick mode**: Any size (metadata only) - <1 second
- **Smart mode**: Files >500MB use URL access (no download) - 2-5 seconds
- **Processing limit**: 5GB maximum for reprojection/COG conversion (Premium Plan memory limit)
- **Full mode**: Files up to 500MB (full download) - 5-30 seconds
- **Queue timeout**: 10 minutes per job
- **HTTP timeout**: 230 seconds

### File Size Limitations

**Current Premium Plan Limits:**
- ✅ Files up to 5GB can be processed (validation, reprojection, COG conversion)
- ⚠️ Files 3-5GB will trigger warnings (approaching memory limits)
- ❌ Files over 5GB will be rejected with clear error message

**Future Enhancement (TODO):**
- Sequential batch processing for very large GeoTIFFs (>5GB)
- Will process large files by splitting into tiles/windows
- Allows processing of any size file without memory constraints

## 🚨 Important Notes

1. **Never create folders with same names as .py files** - causes import conflicts
2. **Use flat file structure** for Azure Functions compatibility
3. **Environment variables must be set** before deployment
4. **PostgreSQL/PostGIS required** for STAC operations
5. **Function keys required** for API access in production

## 📝 License

MIT

## 👥 Contributors

- Robert Harrison (rob634)

## 🔗 Related Resources

- [Azure Functions Python Guide](https://docs.microsoft.com/azure/azure-functions/functions-reference-python)
- [STAC Specification](https://stacspec.org/)
- [PostGIS Documentation](https://postgis.net/documentation/)
- [Cloud Optimized GeoTIFF](https://www.cogeo.org/)