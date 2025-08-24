# Azure Geospatial ETL Pipeline

A production-ready Azure Functions-based geospatial ETL pipeline for processing satellite imagery and geospatial data through Bronze→Silver→Gold tiers with STAC cataloging.

## 🏗️ Architecture Overview

```
HTTP API → Job Queue → Task Queue → Processing Service → Storage/Database
         ↓           ↓                                 ↓
    Job Tracking  Task Tracking                   STAC Catalog
   (Table Storage) (Table Storage)              (PostgreSQL/PostGIS)
```

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

### State Management System

#### `state_models.py`
Data models for job and task state tracking.
- **Job States**: INITIALIZED → PLANNING → PROCESSING → VALIDATING → COMPLETED/FAILED
- **Task States**: QUEUED → PROCESSING → COMPLETED/FAILED
- **Job Types**: `simple_cog` (<4GB), `monster_cog` (>10GB chunked), `multi_merge_cog` (tiled)
- **Validation Levels**: STRICT, STANDARD, LENIENT
- **Message Classes**: JobMessage, TaskMessage for queue communication

#### `state_manager.py`
Manages job and task state persistence in Azure Table Storage.
- **Table Management**: Creates and manages `jobs` and `tasks` tables
- **State Transitions**: Validates and enforces state transition rules
- **Task Counters**: Tracks total, completed, and failed tasks per job
- **Large Metadata Storage**: Stores metadata >64KB in blob storage
- **Job Completion Logic**: Determines when jobs are complete based on task status

#### `state_integration.py`
Bridge between the main application and state management system.
- **Job Submission**: Creates job records and queues initial tasks
- **Task Processing**: Routes queued tasks to appropriate handlers
- **Status Tracking**: Updates job/task status throughout processing
- **Queue Integration**: Handles message encoding/decoding for queues

### Task Processing

#### `task_router.py`
Routes tasks to appropriate processing handlers.
- **Task Dispatch**: Maps task types to handler functions
- **Handler Methods**:
  - `_handle_create_cog`: COG conversion processing
  - `_handle_validate`: Output validation
  - `_handle_analyze_input`: Input analysis (placeholder)
  - `_handle_process_chunk`: Chunk processing (placeholder)
- **Task Chaining**: Automatically queues next task in sequence
- **Error Handling**: Updates task status on failure

#### `output_validator.py`
Validates processing outputs with configurable strictness.
- **Validation Checks**:
  - Output file existence
  - Valid COG format verification
  - Metadata integrity checks
  - File size reasonableness
- **Clean Naming**: Removes tile suffixes (_R1C1, _merged, etc.)
- **Final Path Management**: Moves validated files to final locations
- **Temp Cleanup**: Manages temporary file cleanup

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
func azure functionapp publish rmhgeoapibeta --python

# Check deployment
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/health
```

## 📊 Current Status

### ✅ Working Features
- COG conversion for files up to 5GB
- STAC cataloging with smart mode for 20GB+ files
- State management with job/task tracking
- Blob inventory system handling 1000+ files
- Poison queue monitoring
- Container sync operations
- Metadata inference from filenames

### ⚠️ Known Issues
- Jobs may remain in PROCESSING state after completion
- Nested file paths create duplicated folder structures
- Generic naming for some processed files

### 🎯 Upcoming Features
- Chunked processing for files >10GB (monster_cog)
- Multi-tile scene merging (multi_merge_cog)
- Vector data processing to PostGIS
- GeoParquet exports (Gold tier)
- TiTiler integration for visualization

## 📚 Additional Documentation
See `CLAUDE.md` for detailed technical documentation, deployment instructions, and API examples.

## 📄 License
Proprietary - All rights reserved