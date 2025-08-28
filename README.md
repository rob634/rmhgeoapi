# Azure Geospatial ETL Pipeline

**🚨 DEVELOPMENT ENVIRONMENT - CORE ARCHITECTURE DESIGN**

This is a **development environment** focused on **core architecture design and implementation**. There are no production users, no legacy data, and no backward compatibility requirements. All architectural changes are made with clean design principles prioritizing correctness and maintainability over compatibility.

**Key Development Principles:**
- **No Backward Compatibility**: Breaking changes are acceptable and encouraged for better architecture
- **Explicit Error Handling**: No fallback logic - errors force proper migration to new patterns  
- **Clean Architecture**: Remove deprecated patterns completely rather than maintaining dual support
- **Fast Iteration**: Focus on core design quality without production migration concerns

---

A Azure Functions-based geospatial ETL pipeline for processing satellite imagery and geospatial data through Bronze→Silver→Gold tiers with STAC cataloging.

## 🏗️ Architecture Overview

**Current Architecture**: Clean Job→Task pattern with distributed completion detection

```
HTTP Request → Controller → Job → Task → Queue → Service → Results
         ↓            ↓     ↓                           ↓
    ControllerFactory  Jobs Table  Tasks Table    STAC Catalog
                    (Table Storage)              (PostgreSQL/PostGIS)
```

**Pattern**: Controller → Service → Repository with ABC classes for extensibility

### Request Flow
1. **Controller**: Validates request, creates job and tasks
2. **Job**: Tracks overall operation status and aggregates results
3. **Task**: Individual work unit processed in queue
4. **Service**: Performs actual geospatial processing

### 🎉 Job→Task Architecture Status

#### ✅ What's Proven and Working

**HelloWorldController**: Complete end-to-end validation with multi-task support (n=1 to n=100)
- Job Creation → Task Creation → Queue Processing → Task Completion → Job Aggregation ✅
- Multi-task workflows with comprehensive result statistics ✅
- Distributed completion detection without coordination servers ✅

#### ⚠️ What Needs Validation

**All Other Operations**: Status unknown - need validation to confirm controller pattern adoption
- ContainerController (list_container, sync_container)
- STACController (catalog_file operations)  
- DatabaseMetadataController (list_collections, get_database_summary, etc.)
- RasterController (COG operations)
- TiledRasterController (tiling operations)

**CRITICAL**: Only HelloWorldController has been validated with the clean Job→Task architecture.

### Architecture Benefits

1. **Consistency**: Every operation follows same pattern
2. **Scalability**: Tasks process independently in parallel
3. **Reliability**: Built-in error handling and job completion detection
4. **Maintainability**: Clear separation of concerns between controllers and services
5. **Testability**: Each component can be tested in isolation

## 📦 Module Documentation

### Core Application Entry Points

#### `function_app.py`
Main Azure Functions entry point that defines all HTTP endpoints and queue triggers.
- **HTTP Endpoints**: `/api/health`, `/api/jobs/{operation_type}`, `/api/jobs/{job_id}`
- **Queue Triggers**: `process_job_queue`, `process_task_queue`
- **Timer Triggers**: `monitor_poison_queues` (runs every 5 minutes)
- **Key Features**:
  - Routes job requests to appropriate services
  - Handles queue message processing with Base64 encoding
  - Implements poison queue monitoring for failed messages

### Configuration & Setup

#### `config.py`
Central configuration management for all environment variables and settings.
- **Storage Configuration**: Azure Storage account settings, container names
- **Database Configuration**: PostgreSQL connection settings
- **Raster Processing Config**: COG profiles, compression settings, chunk sizes
- **STAC Configuration**: Collection names, schema settings
- **Smart Mode Thresholds**: File size limits for different processing modes

#### `logger_setup.py`
Centralized logging configuration with consistent formatting.
- Configures Azure Functions logging integration
- Sets up log levels based on environment
- Provides structured logging format with timestamps
- Creates logger instances for all modules

### Job→Task Architecture (NEW - Aug 2025)

#### `base_controller.py`
Abstract base class enforcing Job→Task pattern with validation helpers.
- **Parameter Validation**: DDH parameter checking, request validation
- **Task Creation**: Abstract methods for controller implementations
- **Result Aggregation**: Combines task results into job results
- **Error Handling**: Consistent exception handling across controllers

#### `controller_factory.py`
Routes operations to appropriate controllers based on operation type.
- **Dynamic Routing**: Maps operation types to controller classes
- **Controller Registration**: Centralized controller management
- **Fallback Handling**: Routes unknown operations to legacy services

#### `hello_world_controller.py`
**ONLY PROVEN WORKING CONTROLLER** - Complete end-to-end validation.
- **Multi-task Support**: Creates n tasks (1-100) from single request
- **Architecture Testing**: Primary test case for Job→Task pattern
- **Result Statistics**: Comprehensive hello_statistics aggregation
- **Distributed Completion**: Proven distributed task completion detection

#### `task_manager.py`
Centralized task lifecycle and job completion detection.
- **Task Creation**: Creates task records and queues task messages
- **Completion Detection**: Distributed job completion without coordination
- **Result Aggregation**: Collects task results into job results
- **Status Management**: Updates job status based on task completion

#### `task_router.py`
Clean task processing with TaskManager integration.
- **Task Routing**: Routes tasks to appropriate handler functions
- **TaskManager Integration**: Uses TaskManager for proper lifecycle
- **Handler Registration**: Maps task types to processing functions
- **Result Processing**: Updates task status and checks job completion

### Additional Controllers (Status Unknown - Need Validation)

⚠️ **CRITICAL**: Only HelloWorldController has been validated with the clean Job→Task architecture.

#### `container_controller.py`
Container operations controller - **STATUS UNKNOWN**.
- **Operations**: list_container, sync_container
- **Validation Needed**: Test if using controller pattern vs deprecated service pattern

#### `database_metadata_controller.py` 
Database metadata controller - **STATUS UNKNOWN**.
- **Operations**: list_collections, get_database_summary, database_health
- **Validation Needed**: Test if using controller pattern vs deprecated service pattern

#### Other Controllers
- **STACController**: catalog_file operations - Status unknown
- **RasterController**: COG operations - Status unknown  
- **TiledRasterController**: tiling operations - Status unknown

### Core Services

#### `services.py`
Service factory and base classes for all processing services.
- **ServiceFactory**: Creates and manages service instances
- **BaseService**: Abstract base class for all services
- **Service Registry**: Maps operation types to service implementations
- **Dependency Injection**: Manages service dependencies

#### `repositories.py`
Data access layer for Azure Storage and databases.
- **BlobRepository**: Azure Blob Storage operations
- **TableRepository**: Azure Table Storage operations
- **QueueRepository**: Azure Queue Storage operations
- **Base Repository Pattern**: Common interface for data access

### Raster Processing Services

#### `base_raster_processor.py` (NEW - Aug 2025)
Base class for all raster processors to eliminate code duplication.
- **Shared Storage**: Single StorageRepository instance for all processors
- **Common Methods**: get_blob_url(), check_file_exists(), should_use_smart_mode()
- **Unified Configuration**: Centralized container and folder settings
- **Consistent Error Handling**: Shared error handling patterns
- **Inheritance Hierarchy**: All raster processors extend this base class

#### `raster_processor.py`
Main orchestrator for raster processing workflows.
- **Processing Pipeline**: Validation → Reprojection → COG conversion → STAC cataloging
- **Smart Mode Selection**: Chooses processing mode based on file size
- **Error Recovery**: Handles failures at each processing step
- **Metadata Preservation**: Maintains metadata throughout pipeline
- **Components**: Uses RasterValidator, RasterReprojector, COGConverter (all inherit from BaseRasterProcessor)

#### `raster_validator.py`
Validates raster files and extracts metadata.
- **Format Detection**: Identifies raster format and characteristics
- **CRS Detection**: Extracts coordinate reference system
- **Metadata Extraction**: Gets dimensions, bands, compression info
- **Validation Checks**: Ensures file is processable
- **Inherits From**: BaseRasterProcessor for shared functionality

#### `raster_reprojector.py`
Reprojects rasters to standard coordinate systems.
- **Target CRS**: Default EPSG:4326 (WGS84)
- **Resampling Methods**: Bilinear, cubic, nearest neighbor
- **Memory Management**: Handles large files with windowed processing
- **Preservation**: Maintains nodata values and metadata
- **Inherits From**: BaseRasterProcessor for shared functionality

#### `cog_converter.py`
Converts rasters to Cloud Optimized GeoTIFF format.
- **COG Validation**: Checks if file is already COG format
- **Conversion Profiles**: LZW, DEFLATE, JPEG compression options
- **Tiling Configuration**: Internal tiling for optimal cloud access
- **Overview Generation**: Creates pyramids for multi-resolution access
- **Metadata Extraction**: Comprehensive COG metadata collection
- **Inherits From**: BaseRasterProcessor for shared functionality

### STAC Cataloging

#### `stac_service.py`
Main STAC (SpatioTemporal Asset Catalog) operations service.
- **Mode Selection**: Quick (metadata only), Full (download), Smart (header-only)
- **Collection Management**: Creates/updates STAC collections
- **Item Creation**: Generates STAC items with proper metadata
- **Geometry Extraction**: Gets bounding boxes and footprints

#### `stac_repository.py`
STAC data persistence in PostgreSQL/PostGIS.
- **Table Operations**: Manages `geo.collections` and `geo.items` tables
- **Spatial Queries**: Uses PostGIS for geometry operations
- **Upsert Logic**: Creates or updates STAC records
- **Relationship Management**: Links items to collections

#### `stac_models.py`
STAC data models and validation.
- **Collection Model**: STAC collection structure
- **Item Model**: STAC item with assets and properties
- **Geometry Types**: Polygon, MultiPolygon support
- **Metadata Schemas**: Validates STAC metadata structure

#### `stac_cog_cataloger.py`
Specialized STAC cataloging for COG files.
- **COG Detection**: Identifies Cloud Optimized GeoTIFFs
- **Provenance Tracking**: Records if file was already COG or converted
- **Asset Management**: Creates appropriate asset links
- **Thumbnail Generation**: Creates preview assets (placeholder)
- **Inherits From**: BaseRasterProcessor for shared functionality

#### `stac_catalog_service.py`
Standalone STAC cataloging service for any file type.
- **File Type Detection**: Handles raster, vector, and metadata files
- **Smart Cataloging**: Uses appropriate method based on file type
- **Batch Operations**: Catalogs multiple files efficiently
- **Error Recovery**: Continues cataloging despite individual failures

### Database Management

#### `database_client.py`
PostgreSQL/PostGIS database client with connection pooling.
- **Connection Management**: Handles connection pooling and timeouts
- **Query Execution**: Runs parameterized queries safely
- **Schema Operations**: Creates/manages database schemas
- **Extension Management**: Ensures PostGIS is enabled

#### `database_health.py`
Database health monitoring and diagnostics.
- **Connection Testing**: Verifies database connectivity
- **PostGIS Verification**: Checks spatial extension status
- **Schema Inspection**: Lists tables and structures
- **Performance Metrics**: Monitors query performance

### Container Operations

#### `container_service.py`
Manages Azure Blob Storage container operations.
- **Container Listing**: Lists files with comprehensive statistics
- **Metadata Inference**: Extracts metadata from filenames and paths
- **Vendor Detection**: Identifies Maxar, Planet, Sentinel, Landsat data
- **Tile Detection**: Recognizes multi-tile scenes
- **Relationship Analysis**: Groups related files (sidecars, tiles)

#### `blob_inventory_manager.py`
Manages blob inventories to overcome Table Storage size limits.
- **Inventory Storage**: Stores compressed JSON in blob storage
- **Three-File System**:
  - Full inventory (all files)
  - Geospatial-only inventory
  - Lightweight summary
- **Compression**: 93.5% size reduction using gzip
- **Caching**: Reuses inventory for batch operations

### Queue Management

#### `poison_queue_monitor.py`
Monitors and processes poison queue messages.
- **Automatic Detection**: Finds messages that failed 5+ times
- **Job Status Updates**: Marks failed jobs in Table Storage
- **Batch Processing**: Handles up to 500 messages per run
- **Optional Cleanup**: Can delete processed poison messages
- **Timer Integration**: Runs every 5 minutes automatically

### Container Sync Operations

#### `container_sync_service.py`
Synchronizes entire containers to STAC catalog.
- **Fan-out Pattern**: 1 sync job → many cataloging tasks
- **Progress Tracking**: Updates sync status in real-time
- **Mode Selection**: Auto-selects quick/full/smart per file
- **Error Tolerance**: Continues despite individual failures
- **Inventory Usage**: Uses cached inventory for efficiency

### Utility Modules

#### `raster_chunked_processor.py`
Processes large rasters in chunks.
- **Memory Management**: Processes files too large for memory
- **Chunk Coordination**: Manages chunk assembly
- **Progress Tracking**: Reports chunk processing status
- **Error Recovery**: Handles partial chunk failures
- **Inherits From**: BaseRasterProcessor for shared functionality

#### `geoparquet_exporter.py`
Exports vector data to GeoParquet format (Gold tier).
- **Format Conversion**: Converts various formats to GeoParquet
- **Compression**: Applies Snappy/ZSTD compression
- **Partitioning**: Supports spatial partitioning
- **Metadata Preservation**: Maintains schema and CRS info

### Additional Core Modules

#### `models.py`
Core data models for the application.
- **Job Model**: Represents processing jobs with status tracking
- **JobRequest Model**: Input parameters for job creation
- **JobOperationType Enum**: Defines available operations
- **JobStatus Enum**: Job lifecycle states

### Testing Utilities

#### `test_cog_with_auth.py`
Tests COG processing with proper authentication.
- **Connection String Auth**: Uses storage account key for local testing
- **Task Simulation**: Creates and processes test tasks
- **Status Verification**: Checks job and task status updates
- **Error Debugging**: Provides detailed error output

#### `test_local_state.py`
Tests state management system locally.
- **Table Storage Testing**: Verifies job/task persistence
- **State Transitions**: Tests valid state changes
- **Counter Updates**: Verifies task counting logic
- **Blob References**: Tests large metadata storage

#### `test_task_simulation.py`
Simulates task processing workflows.
- **Task Chain Testing**: Verifies task sequencing
- **Handler Testing**: Tests individual task handlers
- **Queue Simulation**: Simulates queue message flow
- **Timing Analysis**: Measures processing performance

### Scripts

#### `scripts/full_stac_inventory.py`
Processes all files in bronze container to STAC.
- **Batch Processing**: Handles 1000+ files efficiently
- **Progress Reporting**: Shows real-time progress
- **Error Summary**: Reports failed cataloging attempts
- **Mode Analysis**: Shows distribution of quick/full/smart processing

#### `scripts/deploy-dashboard.sh`
Deploys static web dashboard to Azure Storage.
- **Static Site Deployment**: Uploads HTML/JS to $web container
- **CORS Configuration**: Sets allowed origins
- **Cache Control**: Configures browser caching
- **Version Management**: Handles versioned deployments

## 🔑 Key Design Patterns

### 1. **Repository Pattern**
Abstracts data access behind consistent interfaces, making it easy to swap storage implementations.

### 2. **Service Factory Pattern**
Creates service instances based on operation type, enabling dynamic service selection.

### 3. **State Machine Pattern**
Enforces valid state transitions for jobs and tasks, preventing invalid states.

### 4. **Chain of Responsibility**
Tasks automatically queue their successors, creating processing chains.

### 5. **Circuit Breaker**
Prevents processing of suspiciously large files (>100GB) without manual review.

### 6. **Smart Mode Selection**
Automatically chooses optimal processing mode based on file characteristics.

## 🚀 Getting Started

### Prerequisites
- Python 3.12
- Azure Functions Core Tools
- Azure Storage Account
- PostgreSQL with PostGIS extension
- GDAL/rasterio libraries

### Environment Variables
```bash
# Azure Storage
STORAGE_ACCOUNT_NAME=rmhazuregeo
AZURE_WEBJOBS_STORAGE=<connection_string>

# Containers
BRONZE_CONTAINER_NAME=rmhazuregeobronze
SILVER_CONTAINER_NAME=rmhazuregeosilver
GOLD_CONTAINER_NAME=rmhazuregeogold

# Database
POSTGIS_HOST=rmhpgflex.postgres.database.azure.com
POSTGIS_DATABASE=geopgflex
POSTGIS_USER=rob634
POSTGIS_PASSWORD=<password>
POSTGIS_SCHEMA=geo

# Processing
SILVER_TEMP_FOLDER=temp
SILVER_COGS_FOLDER=cogs
SILVER_CHUNKS_FOLDER=chunks
```

### Local Development
```bash
# Install dependencies
pip install -r requirements.txt

# Run function app locally
func start

# Test health endpoint
curl http://localhost:7071/api/health
```

### Deployment
```bash
# Deploy to Azure
func azure functionapp publish rmhgeoapibeta --build remote

# Check deployment
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/health
```

## 🏗️ Infrastructure Setup & Management

The system includes comprehensive infrastructure initialization that automatically ensures all required Azure resources exist and are properly configured.

### ✅ Automatic Infrastructure Creation

**What Gets Created Automatically**:
- **Azure Storage Tables**: Jobs, Tasks (with proper schemas)
- **Azure Storage Queues**: geospatial-jobs, geospatial-tasks, poison queues  
- **PostgreSQL STAC Schema**: geo.collections, geo.items tables (optional)
- **Health monitoring**: Table and queue accessibility validation

**When It Initializes**:
- **First health check**: `/api/health`
- **First job submission**: `/api/jobs/{operation}`
- **Manual trigger**: `/api/infrastructure`

### 📊 Infrastructure Components

#### Storage Tables
| Table | Purpose | Key Fields |
|-------|---------|------------|
| **Jobs** | Job lifecycle tracking | `job_id`, `status`, `job_type`, `dataset_id`, `resource_id`, `result_data` |
| **Tasks** | Task execution tracking | `task_id`, `parent_job_id`, `status`, `task_type`, `task_data` |

#### Storage Queues
| Queue | Purpose |
|-------|---------|
| **geospatial-jobs** | Job processing queue |
| **geospatial-tasks** | Task processing queue |
| **geospatial-jobs-poison** | Failed job messages |
| **geospatial-tasks-poison** | Failed task messages |

#### Database Schema (Optional)
| Component | Purpose |
|-----------|---------|
| **geo schema** | PostgreSQL schema for STAC data |
| **geo.collections** | STAC collections table |
| **geo.items** | STAC items table |

### 🔧 Infrastructure Management APIs

#### Check Infrastructure Status
```bash
GET /api/infrastructure
```
Response:
```json
{
  "initialized": true,
  "status": {
    "tables_created": ["Jobs", "Tasks"],
    "tables_validated": ["Jobs", "Tasks"],  
    "queues_created": ["geospatial-jobs", "geospatial-tasks"],
    "overall_success": true
  },
  "health": {
    "tables": {"Jobs": {"status": "healthy"}},
    "queues": {"geospatial-jobs": {"status": "healthy", "message_count": 0}}
  }
}
```

#### Force Infrastructure Re-initialization
```bash
curl -X POST /api/infrastructure \
  -H "Content-Type: application/json" \
  -d '{"force_reinit": true}'
```

### 🧪 Testing Infrastructure

#### Comprehensive Test Suite
```bash
# Set environment variables
export STORAGE_ACCOUNT_NAME="your_storage_account"
export AzureWebJobsStorage="DefaultEndpointsProtocol=https;..."

# Run infrastructure tests
python test_infrastructure_init.py
```

#### Expected Test Output
```
🧪 Testing Infrastructure Initialization Service
============================================================
📋 Configuration:
  Storage Account: rmhazuregeo
  PostgreSQL Host: rmhpgflex.postgres.database.azure.com

✅ All tests PASSED!
✅ Tables: 2/2 healthy
✅ Queues: 4/4 healthy
✅ Idempotency: Working correctly
✅ Database: Initialized successfully
```

### 🔧 Troubleshooting

#### Common Issues
**❌ Missing STORAGE_ACCOUNT_NAME**
```bash
# Solution: Set environment variable
export STORAGE_ACCOUNT_NAME="rmhazuregeo"
```

**❌ Permission denied on table/queue creation**
```bash
# Solution: Ensure managed identity has Storage Contributor role
```

**❌ Database connection failures**
```bash
# Solution: Check POSTGIS_* environment variables and firewall rules
```

#### Manual Recovery
```bash
# Force complete re-initialization
curl -X POST /api/infrastructure \
  -H "Content-Type: application/json" \
  -d '{"force_reinit": true, "include_database": true}'
```

### 📋 Best Practices

1. **Let it initialize automatically** - First health check will set up infrastructure
2. **Monitor infrastructure endpoint** - Use `/api/infrastructure` for status monitoring  
3. **Test after deployment** - Run infrastructure tests after each deployment
4. **Check poison queues** - Use `/api/monitor/poison` to check for failed messages
5. **Database is optional** - System works without PostgreSQL, just no STAC features

## 📊 Current Status (Updated August 28, 2025)

### ✅ Architecture Status

**HelloWorldController**: ✅ **FULLY OPERATIONAL** - Complete end-to-end workflow validated
- Job Creation → Task Creation → Queue Processing → Task Completion → Job Aggregation ✅
- Multi-task workflows (n=1 to n=100) with comprehensive result statistics ✅
- Distributed completion detection without coordination servers ✅

**All Other Operations**: ⚠️ **STATUS UNKNOWN** - Need validation with clean Job→Task architecture
- ContainerController (list_container, sync_container) - Unknown if using controller pattern
- STACController (catalog_file operations) - Unknown if using controller pattern  
- DatabaseMetadataController (metadata operations) - Unknown if using controller or service pattern
- RasterController (COG operations) - Unknown if implemented with controller pattern
- TiledRasterController (tiling operations) - Unknown if implemented with controller pattern

### ✅ Working Features
- **Job→Task Architecture**: Complete with HelloWorldController as proven template
- **STAC cataloging**: Smart mode for 20GB+ files with 270+ items cataloged
- **Blob inventory system**: Handling 1,157 files (87.96 GB) in bronze container
- **Poison queue monitoring**: Automatic failed job detection and cleanup
- **Infrastructure initialization**: Automatic table/queue creation on deployment
- **Distributed completion**: No coordination servers needed for job completion

### ⚠️ Immediate Priorities
1. **Validate existing operations**: Test list_container, sync_container for controller pattern usage
2. **Implement sequential task chaining**: Required for vector and raster processing workflows  
3. **Test integration**: Verify end-to-end workflows for each operation type
4. **Convert service pattern operations**: Update any operations still using direct service calls

### 🎯 Future Features
- **Sequential job chaining framework**: Multi-stage workflows (job chaining with stage management)
- **Vector processing**: Sequential preprocessing → parallel PostGIS upload  
- **Tiled raster processing**: Orchestrator → N parallel tiles → N COGs
- **GeoParquet exports**: Gold tier analysis-ready products

## 📚 Additional Documentation
See `CLAUDE.md` for detailed technical documentation, deployment instructions, and API examples.

## 📄 License
Proprietary - All rights reserved