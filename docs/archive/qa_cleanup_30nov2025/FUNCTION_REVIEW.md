# Azure Functions Inventory - Complete API Reference

**Generated**: 13 NOV 2025
**Function App**: rmhazuregeoapi (B3 Basic tier)
**Total Functions**: 80
**Environment**: Development (Monolith) → Production (Microservices)

---

## 🎯 Development Philosophy: "Claude Code as the Developer"

**Problem**: Direct database connections blocked on corporate network (no DBeaver, no pgAdmin)

**Solution**: "How do I make API endpoints that give 'the developer' (Claude Code) complete visibility into all app systems?"

**Result**: 80 HTTP endpoints providing complete system introspection:
- Database schemas, tables, queries, locks, connections
- Service Bus queues, messages, dead-letters
- Job/task execution state, parameters, results
- STAC catalog browsing
- OGC feature collections
- Platform orchestration tracking

**Design Principle**: If Claude Code can't access the database directly, give Claude Code HTTP endpoints that expose everything the database knows.

---

## 🏗️ Architecture Evolution: Development → Production

### Current State: Development Monolith (80 functions in one app)
**Purpose**: Develop all components together for rapid iteration
- Single codebase, single deployment
- Shared dependencies, shared config
- Easy cross-component debugging
- No network latency between components

### Future State: Production Microservices (4 function apps)

```
┌─────────────────────────────────────────────────────────────┐
│                   Azure API Management (APIM)                │
│              Custom Domain: geospatial.rmh.org               │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐   ┌──────────────────┐   ┌──────────────┐
│  STAC API     │   │  OGC Features    │   │  Platform    │
│  Function App │   │  Function App    │   │  Function App│
│  (16 funcs)   │   │  (7 funcs)       │   │  (5 funcs)   │
│               │   │                  │   │              │
│  Public:      │   │  Public:         │   │  Internal:   │
│  - Search     │   │  - Collections   │   │  - Ingest    │
│  - Browse     │   │  - Features      │   │  - Status    │
│  - Metadata   │   │  - Bbox query    │   │  - Cancel    │
└───────────────┘   └──────────────────┘   └──────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │  CoreMachine     │
                    │  Function App    │
                    │  (Internal Only) │
                    │  - Job execution │
                    │  - Task workers  │
                    │  - H3 grid       │
                    └──────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │  PostgreSQL      │
                    │  (Shared DB)     │
                    │  - geo schema    │
                    │  - pgstac schema │
                    │  - platform sch. │
                    │  - app schema    │
                    └──────────────────┘
```

### Production Deployment Strategy

#### External Access (APIM Routing)
1. **STAC API** (`/api/collections/*`)
   - **Access**: Public (Azure AD tenant users)
   - **Purpose**: Metadata search and discovery
   - **Function App**: `rmhazuregeoapi-stac`
   - **Audience**: Data scientists, GIS analysts, web applications

2. **OGC Features API** (`/api/features/*`)
   - **Access**: Public (Azure AD tenant users)
   - **Purpose**: Vector feature access (standards-compliant)
   - **Function App**: `rmhazuregeoapi-ogc`
   - **Audience**: GIS software, web maps, spatial queries

3. **Platform API** (`/api/platform/*`)
   - **Access**: Internal (DDH app + approved applications only)
   - **Purpose**: Data ingestion orchestration
   - **Function App**: `rmhazuregeoapi-platform`
   - **Audience**: Automated ETL, DDH integration, admin tools

#### Internal Only (No APIM Exposure)
4. **CoreMachine API** (No external routes)
   - **Access**: Internal (Function Apps + Service Bus only)
   - **Purpose**: Low-level job/task execution
   - **Function App**: `rmhazuregeoapi-coremachine`
   - **Audience**: Platform layer, Service Bus processors

5. **Admin Endpoints** (Development only, removed in production)
   - Database admin (`/api/dbadmin/*`)
   - Service Bus admin (`/api/servicebus/admin/*`)
   - Debug endpoints (`/api/db/debug/*`)
   - H3 debug endpoints (`/api/h3/debug/*`)
   - **Removed in production** - Replace with proper monitoring (Application Insights, Log Analytics)

### Why This Architecture?

#### Development Benefits (Current)
- ✅ **Rapid Development**: All code in one place
- ✅ **Easy Debugging**: Complete system visibility via HTTP
- ✅ **No Network Overhead**: All calls in-process
- ✅ **Simple Deployment**: Single `func publish` command
- ✅ **Shared Dependencies**: One requirements.txt

#### Production Benefits (Future)
- ✅ **Independent Scaling**: Scale STAC API separately from Platform
- ✅ **Security Isolation**: Public APIs can't access CoreMachine
- ✅ **Deployment Independence**: Update OGC Features without touching STAC
- ✅ **Cost Optimization**: Different tiers for different workloads
- ✅ **Standards Compliance**: Clean API boundaries for STAC/OGC
- ✅ **Failure Isolation**: STAC failure doesn't affect Platform ingestion

### Migration Path

**Phase 1: Current (Development)**
- Monolith with 80 functions
- All admin/debug endpoints available
- Rapid iteration, learning, prototyping

**Phase 2: Pre-Production (Testing)**
- Extract STAC/OGC to separate apps
- Keep admin endpoints for troubleshooting
- Test APIM routing configuration
- Validate inter-app communication

**Phase 3: Production (Locked Down)**
- Remove all admin/debug endpoints
- Platform API as only external integration point
- STAC/OGC for public data access (read-only)
- CoreMachine completely internal
- Full monitoring via Application Insights

### Endpoint Consolidation Candidates

**Current**: 80 functions (many redundant for debugging)

**Production Target**: ~35 functions across 4 apps
- STAC API: 16 functions (no change - standards-compliant)
- OGC Features: 7 functions (no change - standards-compliant)
- Platform API: 5 functions (public interface)
- CoreMachine: 7 functions (internal job/task execution)
- **Remove**: 45 admin/debug functions (replaced with proper monitoring)

**Admin Endpoints to Remove in Production**:
- All `/api/dbadmin/*` (17 functions) → Use Log Analytics KQL queries
- All `/api/servicebus/admin/*` (6 functions) → Use Azure Portal monitoring
- All `/api/db/debug/*` (8 functions) → Use Application Insights
- All `/api/h3/debug/*` (8 functions) → Use Application Insights
- Nuclear buttons (`nuke`, `redeploy`) (3 functions) → Azure Portal only

**Why Keep Admin Endpoints in Development**:
1. **Corporate Network Restrictions**: Can't connect directly to PostgreSQL
2. **Claude Code Development**: AI needs HTTP visibility into system state
3. **Rapid Debugging**: No context switching to Azure Portal
4. **Learning Phase**: Understanding data flows, schema evolution
5. **Partridge in a Pear Tree**: Because why the hell not! 🎄

---

## Table of Contents

1. [System Health & Monitoring](#system-health--monitoring) (1)
2. [Database Administration](#database-administration) (17)
3. [Service Bus Administration](#service-bus-administration) (6)
4. [Job/Task CoreMachine](#jobtask-coremachine) (7)
5. [STAC API (v1.0 Compliant)](#stac-api-v10-compliant) (16)
6. [OGC Features API (Core 1.0 Compliant)](#ogc-features-api-core-10-compliant) (7)
7. [Platform Layer (Data Ingestion)](#platform-layer-data-ingestion) (5)
8. [H3 Geospatial Grid System](#h3-geospatial-grid-system) (11)
9. [DDH Integration (External System)](#ddh-integration-external-system) (1)
10. [Service Bus Processors (Background)](#service-bus-processors-background) (9)

---

## System Health & Monitoring

### 1. `health`
**Endpoint**: `GET /api/health`
**Purpose**: Application health check with component status
**Returns**: Health status of PostgreSQL, DuckDB, GDAL/VSI, imports, and application insights
**Use Case**: Azure App Service health monitoring, deployment verification
**Version**: v2025-11-13_B3_OPTIMIZED

---

## Database Administration

### 2. `db_schemas_list`
**Endpoint**: `GET /api/dbadmin/schemas`
**Purpose**: List all PostgreSQL schemas
**Returns**: Schema names, sizes, table counts
**Use Case**: Database exploration, schema inventory

### 3. `db_schema_details`
**Endpoint**: `GET /api/dbadmin/schemas/{schema}`
**Purpose**: Detailed schema information
**Returns**: Tables, views, functions, extensions for specific schema
**Use Case**: Deep-dive into schema structure

### 4. `db_schema_tables`
**Endpoint**: `GET /api/dbadmin/schemas/{schema}/tables`
**Purpose**: List tables in a schema
**Returns**: Table names, row counts, sizes
**Use Case**: Schema table inventory

### 5. `db_table_details`
**Endpoint**: `GET /api/dbadmin/tables/{schema}/{table}`
**Purpose**: Detailed table metadata
**Returns**: Columns, types, constraints, indexes
**Use Case**: Table structure inspection

### 6. `db_table_sample`
**Endpoint**: `GET /api/dbadmin/tables/{schema}/{table}/sample`
**Purpose**: Sample rows from table
**Returns**: First N rows (default 10, max 100)
**Use Case**: Quick data preview without DBeaver

### 7. `db_table_columns`
**Endpoint**: `GET /api/dbadmin/tables/{schema}/{table}/columns`
**Purpose**: Column definitions
**Returns**: Column names, types, nullability, defaults
**Use Case**: Schema documentation

### 8. `db_table_indexes`
**Endpoint**: `GET /api/dbadmin/tables/{schema}/{table}/indexes`
**Purpose**: Index information
**Returns**: Index names, columns, types, sizes
**Use Case**: Query optimization

### 9. `db_queries_running`
**Endpoint**: `GET /api/dbadmin/queries/running`
**Purpose**: Active PostgreSQL queries
**Returns**: Query text, duration, state, PID
**Use Case**: Performance troubleshooting

### 10. `db_queries_slow`
**Endpoint**: `GET /api/dbadmin/queries/slow`
**Purpose**: Slow query log (configurable threshold)
**Returns**: Long-running queries with execution stats
**Use Case**: Performance optimization

### 11. `db_locks`
**Endpoint**: `GET /api/dbadmin/locks`
**Purpose**: Database locks
**Returns**: Lock types, blocking queries, wait times
**Use Case**: Deadlock debugging

### 12. `db_connections`
**Endpoint**: `GET /api/dbadmin/connections`
**Purpose**: Active database connections
**Returns**: Connection count, user, state, query
**Use Case**: Connection pool monitoring

### 13. `db_health`
**Endpoint**: `GET /api/dbadmin/health`
**Purpose**: Database health metrics
**Returns**: Connection count, cache hit ratio, lock count
**Use Case**: Database monitoring dashboard

### 14. `db_health_performance`
**Endpoint**: `GET /api/dbadmin/health/performance`
**Purpose**: Performance metrics
**Returns**: Table sizes, index usage, query stats
**Use Case**: Performance analysis

### 15. `db_maintenance_nuke`
**Endpoint**: `POST /api/db/schema/nuke?confirm=yes`
**Purpose**: **NUCLEAR OPTION** - Drop all schemas and data
**Returns**: Destruction summary
**Use Case**: DEV/TEST ONLY - Complete database reset
**⚠️ DANGER**: Irreversible data loss

### 16. `db_maintenance_redeploy`
**Endpoint**: `POST /api/db/schema/redeploy?confirm=yes`
**Purpose**: Nuke + redeploy all schemas in one operation
**Returns**: Deployment summary
**Use Case**: Fresh schema deployment after code changes
**⚠️ DANGER**: Destroys all data

### 17. `db_maintenance_cleanup`
**Endpoint**: `POST /api/dbadmin/maintenance/cleanup`
**Purpose**: VACUUM, ANALYZE, dead tuple cleanup
**Returns**: Cleanup statistics
**Use Case**: Database maintenance

### 18. `admin_db_debug_all`
**Endpoint**: `GET /api/db/debug/all?limit=100`
**Purpose**: Comprehensive database dump (jobs + tasks)
**Returns**: All CoreMachine jobs and tasks with metadata
**Use Case**: System-wide debugging without DBeaver

---

## Service Bus Administration

### 19. `servicebus_admin_list_queues`
**Endpoint**: `GET /api/servicebus/admin/queues`
**Purpose**: List all Service Bus queues
**Returns**: Queue names, message counts, dead-letter counts
**Use Case**: Queue monitoring

### 20. `servicebus_admin_queue_details`
**Endpoint**: `GET /api/servicebus/admin/queues/{queue_name}`
**Purpose**: Detailed queue statistics
**Returns**: Active messages, size, oldest message age
**Use Case**: Queue health check

### 21. `servicebus_admin_peek_messages`
**Endpoint**: `GET /api/servicebus/admin/queues/{queue_name}/peek`
**Purpose**: Peek at messages without dequeueing
**Returns**: Message bodies, properties, enqueue time
**Use Case**: Queue content inspection

### 22. `servicebus_admin_peek_deadletter`
**Endpoint**: `GET /api/servicebus/admin/queues/{queue_name}/deadletter/peek`
**Purpose**: Peek at dead-letter messages
**Returns**: Failed messages with error details
**Use Case**: Failure analysis

### 23. `servicebus_admin_health`
**Endpoint**: `GET /api/servicebus/admin/health`
**Purpose**: Service Bus connectivity health
**Returns**: Connection status, queue availability
**Use Case**: Integration testing

### 24. `servicebus_admin_nuke_queue`
**Endpoint**: `POST /api/servicebus/admin/queues/{queue_name}/nuke?confirm=yes`
**Purpose**: **NUCLEAR OPTION** - Purge all messages from queue
**Returns**: Deletion count
**Use Case**: DEV/TEST ONLY - Queue cleanup
**⚠️ DANGER**: Irreversible message loss

---

## Job/Task CoreMachine

### 25. `submit_job`
**Endpoint**: `POST /api/jobs/submit/{job_type}`
**Purpose**: Submit new job for processing
**Returns**: Job ID, status, submission timestamp
**Use Case**: Trigger background workflows (hello_world, raster_ingest, etc.)

### 26. `get_job_status`
**Endpoint**: `GET /api/jobs/status/{job_id}`
**Purpose**: Query job execution status
**Returns**: Job state, stage, progress, task results
**Use Case**: Poll job completion

### 27. `admin_query_jobs`
**Endpoint**: `GET /api/db/jobs?status=failed&limit=10`
**Purpose**: Query jobs with filters
**Returns**: Filtered job list with metadata
**Use Case**: Failed job analysis, audit trail

### 28. `admin_query_job_by_id`
**Endpoint**: `GET /api/db/jobs/{job_id}`
**Purpose**: Get specific job details
**Returns**: Full job record with parameters and results
**Use Case**: Job debugging

### 29. `admin_query_tasks`
**Endpoint**: `GET /api/db/tasks?status=failed&limit=20`
**Purpose**: Query tasks with filters
**Returns**: Filtered task list
**Use Case**: Task-level debugging

### 30. `admin_query_task_details`
**Endpoint**: `GET /api/db/tasks/{job_id}`
**Purpose**: Get all tasks for a job
**Returns**: Task list with execution details
**Use Case**: Job→Task workflow inspection

### 31. `admin_db_stats`
**Endpoint**: `GET /api/db/stats`
**Purpose**: Database statistics and metrics
**Returns**: Table counts, schema sizes, performance stats
**Use Case**: System health dashboard

---

## STAC API (v1.0 Compliant)

**Standard**: [STAC Specification v1.0.0](https://stacspec.org/)
**Backend**: pgSTAC (PostgreSQL extension)
**Purpose**: Spatiotemporal Asset Catalog for geospatial metadata discovery

### 32. `stac_landing`
**Endpoint**: `GET /api/collections`
**Purpose**: STAC API landing page
**Returns**: API metadata, links to collections/search
**Standard**: STAC Core

### 33. `stac_conformance`
**Endpoint**: `GET /api/conformance`
**Purpose**: STAC conformance classes
**Returns**: List of supported STAC extensions
**Standard**: STAC Core

### 34. `stac_collections_list`
**Endpoint**: `GET /api/collections`
**Purpose**: List all STAC collections
**Returns**: Collection summaries with extents, licenses
**Standard**: STAC Collections

### 35. `stac_collection_details`
**Endpoint**: `GET /api/collections/{collection_id}`
**Purpose**: Get single collection metadata
**Returns**: Full collection object with spatial/temporal extent
**Standard**: STAC Collections

### 36. `stac_items_list`
**Endpoint**: `GET /api/collections/{collection_id}/items`
**Purpose**: List items in collection (paginated)
**Returns**: GeoJSON FeatureCollection of STAC items
**Standard**: STAC Features

### 37. `stac_item_details`
**Endpoint**: `GET /api/collections/{collection_id}/items/{item_id}`
**Purpose**: Get single STAC item
**Returns**: GeoJSON Feature with assets and metadata
**Standard**: STAC Features

### 38. `stac_search_post`
**Endpoint**: `POST /api/search`
**Purpose**: STAC search with complex filters (bbox, datetime, CQL2)
**Returns**: Matching STAC items
**Standard**: STAC Search, CQL2 Filter

### 39. `stac_search_get`
**Endpoint**: `GET /api/search?bbox=-180,-90,180,90`
**Purpose**: STAC search via query parameters
**Returns**: Matching STAC items
**Standard**: STAC Search

### 40. `stac_nuke`
**Endpoint**: `POST /api/stac/nuke?confirm=yes&mode=all`
**Purpose**: **NUCLEAR OPTION** - Delete STAC items/collections
**Returns**: Deletion count
**Use Case**: DEV/TEST ONLY - Clear STAC catalog
**⚠️ DANGER**: Irreversible data loss
**Modes**: `all`, `items`, `collections`

### 41. `stac_collection_create`
**Endpoint**: `POST /api/collections`
**Purpose**: Create new STAC collection
**Returns**: Created collection ID
**Standard**: STAC Transaction Extension

### 42. `stac_collection_update`
**Endpoint**: `PUT /api/collections/{collection_id}`
**Purpose**: Update collection metadata
**Returns**: Updated collection
**Standard**: STAC Transaction Extension

### 43. `stac_collection_delete`
**Endpoint**: `DELETE /api/collections/{collection_id}`
**Purpose**: Delete collection (CASCADE deletes items)
**Returns**: Deletion confirmation
**Standard**: STAC Transaction Extension

### 44. `stac_item_create`
**Endpoint**: `POST /api/collections/{collection_id}/items`
**Purpose**: Add STAC item to collection
**Returns**: Created item ID
**Standard**: STAC Transaction Extension

### 45. `stac_item_update`
**Endpoint**: `PUT /api/collections/{collection_id}/items/{item_id}`
**Purpose**: Update STAC item
**Returns**: Updated item
**Standard**: STAC Transaction Extension

### 46. `stac_item_delete`
**Endpoint**: `DELETE /api/collections/{collection_id}/items/{item_id}`
**Purpose**: Delete STAC item
**Returns**: Deletion confirmation
**Standard**: STAC Transaction Extension

### 47. `stac_items_bulk_create`
**Endpoint**: `POST /api/collections/{collection_id}/items/bulk`
**Purpose**: Bulk create STAC items (batch)
**Returns**: Created item count
**Standard**: STAC Transaction Extension

---

## OGC Features API (Core 1.0 Compliant)

**Standard**: [OGC API - Features - Part 1: Core 1.0](https://www.ogc.org/standards/ogcapi-features)
**Backend**: PostGIS (direct geometry queries)
**Purpose**: Vector feature access via OGC standards

### 48. `ogc_features_landing`
**Endpoint**: `GET /api/features`
**Purpose**: OGC Features API landing page
**Returns**: API metadata, links to collections
**Standard**: OGC Core

### 49. `ogc_features_conformance`
**Endpoint**: `GET /api/features/conformance`
**Purpose**: OGC conformance classes
**Returns**: List of supported OGC standards
**Standard**: OGC Core

### 50. `ogc_features_collections`
**Endpoint**: `GET /api/features/collections`
**Purpose**: List vector collections (from PostGIS geometry_columns)
**Returns**: Collection list with bbox, geometry type
**Standard**: OGC Core

### 51. `ogc_features_collection_details`
**Endpoint**: `GET /api/features/collections/{collection_id}`
**Purpose**: Get collection metadata
**Returns**: Extent, feature count, CRS, geometry type
**Standard**: OGC Core

### 52. `ogc_features_collection_queryables`
**Endpoint**: `GET /api/features/collections/{collection_id}/queryables`
**Purpose**: List queryable properties (column names)
**Returns**: Property names and types for filtering
**Standard**: OGC Filter Extension

### 53. `ogc_features_items`
**Endpoint**: `GET /api/features/collections/{collection_id}/items?bbox=-70,-56,-69,-55&limit=10`
**Purpose**: Query features with spatial/attribute filters
**Returns**: GeoJSON FeatureCollection
**Standard**: OGC Core + CRS Extension
**Filters**: bbox, limit, offset, CRS

### 54. `ogc_features_item_details`
**Endpoint**: `GET /api/features/collections/{collection_id}/items/{feature_id}`
**Purpose**: Get single feature by ID
**Returns**: GeoJSON Feature
**Standard**: OGC Core

---

## Platform Layer (Data Ingestion)

**Purpose**: High-level data ingestion orchestration (Platform schema)

### 55. `platform_submit_ingest_raster`
**Endpoint**: `POST /api/platform/ingest/raster`
**Purpose**: Submit raster dataset ingestion request
**Returns**: Request ID, orchestration job IDs
**Use Case**: Ingest GeoTIFF/COG into system

### 56. `platform_submit_ingest_vector`
**Endpoint**: `POST /api/platform/ingest/vector`
**Purpose**: Submit vector dataset ingestion request
**Returns**: Request ID, orchestration job IDs
**Use Case**: Ingest Shapefile/GeoPackage into PostGIS

### 57. `platform_status_request`
**Endpoint**: `GET /api/platform/status/request/{request_id}`
**Purpose**: Query platform request status
**Returns**: Request state, orchestration jobs, progress
**Use Case**: Track ingestion progress

### 58. `platform_status_orchestration`
**Endpoint**: `GET /api/platform/status/orchestration/{request_id}`
**Purpose**: Get orchestration job details for request
**Returns**: Orchestration job list with CoreMachine job IDs
**Use Case**: Multi-job workflow tracking

### 59. `platform_cancel_request`
**Endpoint**: `POST /api/platform/cancel/{request_id}`
**Purpose**: Cancel platform request and all orchestration jobs
**Returns**: Cancellation confirmation
**Use Case**: Abort failed ingestion

### 60. `admin_api_requests_query`
**Endpoint**: `GET /api/db/api_requests?status=processing&limit=10`
**Purpose**: Query platform API requests with filters
**Returns**: Filtered request list
**Use Case**: Platform layer debugging

### 61. `admin_api_request_details`
**Endpoint**: `GET /api/db/api_requests/{request_id}`
**Purpose**: Get specific API request details
**Returns**: Full request record with parameters
**Use Case**: Platform request debugging

### 62. `admin_orchestration_jobs_query`
**Endpoint**: `GET /api/db/orchestration_jobs?request_id={request_id}`
**Purpose**: Query orchestration jobs
**Returns**: Filtered orchestration job list
**Use Case**: Platform→CoreMachine linking

### 63. `admin_orchestration_jobs_by_request`
**Endpoint**: `GET /api/db/orchestration_jobs/{request_id}`
**Purpose**: Get orchestration jobs for specific request
**Returns**: Orchestration job list with CoreMachine job IDs
**Use Case**: Platform workflow inspection

### 64. `admin_db_functions_test`
**Endpoint**: `GET /api/db/functions/test`
**Purpose**: Test PostgreSQL functions (pgSTAC, platform)
**Returns**: Function test results
**Use Case**: Schema validation

### 65. `admin_db_enums_diagnostic`
**Endpoint**: `GET /api/db/enums/diagnostic`
**Purpose**: Diagnose enum type issues
**Returns**: Enum definitions, mismatches
**Use Case**: Schema debugging

---

## H3 Geospatial Grid System

**Purpose**: Uber H3 hierarchical hexagonal grid for global geospatial indexing

### 66. `h3_bootstrap_submit`
**Endpoint**: `POST /api/h3/bootstrap/submit`
**Purpose**: Submit H3 grid bootstrap job (resolution 0-7)
**Returns**: Job ID for grid generation
**Use Case**: Initialize H3 global grid

### 67. `h3_bootstrap_status`
**Endpoint**: `GET /api/h3/bootstrap/status/{job_id}`
**Purpose**: Query H3 bootstrap job status
**Returns**: Grid generation progress, cell counts
**Use Case**: Monitor grid creation

### 68. `h3_debug_grids_summary`
**Endpoint**: `GET /api/h3/debug/grids/summary`
**Purpose**: Summary of all H3 grids by resolution
**Returns**: Grid metadata for res 0-7
**Use Case**: H3 system health check

### 69. `h3_debug_grid_details`
**Endpoint**: `GET /api/h3/debug/grids/{grid_id}?include_sample=true`
**Purpose**: Detailed H3 grid information
**Returns**: Grid stats, bbox, sample cells
**Use Case**: H3 grid inspection

### 70. `h3_debug_reference_filters`
**Endpoint**: `GET /api/h3/debug/reference_filters`
**Purpose**: List H3 reference filters (precomputed subsets)
**Returns**: Filter metadata, array lengths
**Use Case**: H3 filter inventory

### 71. `h3_debug_reference_filter_details`
**Endpoint**: `GET /api/h3/debug/reference_filters/{filter_name}?include_ids=true`
**Purpose**: Get H3 reference filter details
**Returns**: Filter metadata, H3 cell IDs
**Use Case**: H3 filter inspection

### 72. `h3_debug_sample_cells`
**Endpoint**: `GET /api/h3/debug/sample_cells?grid_id=res2_global&limit=10`
**Purpose**: Sample H3 cells from grid
**Returns**: Cell geometries, properties
**Use Case**: H3 cell visualization

### 73. `h3_debug_parent_child`
**Endpoint**: `GET /api/h3/debug/parent_child/{parent_id}`
**Purpose**: H3 parent-child hierarchy validation
**Returns**: Parent cell + 7 children with validation
**Use Case**: H3 hierarchy testing

### 74. `h3_test_submit_create_grid`
**Endpoint**: `POST /api/h3/test/submit/create_grid`
**Purpose**: Test H3 grid creation job
**Returns**: Test job ID
**Use Case**: H3 workflow testing

### 75. `h3_test_grid_status`
**Endpoint**: `GET /api/h3/test/grid_status/{grid_id}`
**Purpose**: Test H3 grid status query
**Returns**: Grid metadata
**Use Case**: H3 testing

### 76. `h3_test_validate_grid`
**Endpoint**: `POST /api/h3/test/validate_grid/{grid_id}`
**Purpose**: Validate H3 grid integrity
**Returns**: Validation results
**Use Case**: H3 quality assurance

---

## DDH Integration (External System)

**Purpose**: Integration with Distributed Data Hub (DDH) external system

### 77. `ddh_satellite_raster_ingestion`
**Endpoint**: `POST /api/ddh/ingest/satellite/raster`
**Purpose**: DDH satellite raster ingestion trigger
**Returns**: Platform request ID
**Use Case**: Automated satellite imagery ingestion from DDH

---

## Service Bus Processors (Background)

**Purpose**: Background workers triggered by Service Bus messages (not HTTP endpoints)

### 78. `process_dataset_ingestion_request`
**Trigger**: Service Bus queue `dataset-ingestion-requests`
**Purpose**: Process platform ingestion requests
**Action**: Create orchestration jobs, spawn CoreMachine jobs
**Use Case**: Platform→CoreMachine orchestration

### 79. `process_raster_metadata_extract`
**Trigger**: Service Bus queue `raster-metadata-extract`
**Purpose**: Extract raster metadata (GDAL)
**Action**: Read GeoTIFF, extract CRS/extent/bands
**Use Case**: Raster ETL step 1

### 80. `process_raster_stage_validation`
**Trigger**: Service Bus queue `raster-stage-validation`
**Purpose**: Validate raster for COG conversion
**Action**: Check file integrity, CRS validity
**Use Case**: Raster ETL step 2

### 81. `process_raster_cog_generation`
**Trigger**: Service Bus queue `raster-cog-generation`
**Purpose**: Convert raster to Cloud-Optimized GeoTIFF
**Action**: GDAL COG conversion with tiling
**Use Case**: Raster ETL step 3

### 82. `process_stac_creation`
**Trigger**: Service Bus queue `stac-creation`
**Purpose**: Create STAC item for ingested dataset
**Action**: Generate STAC JSON, register with pgSTAC
**Use Case**: Metadata catalog update

### 83. `process_qgis_project_update`
**Trigger**: Service Bus queue `qgis-project-update`
**Purpose**: Update QGIS project files
**Action**: Add new layers to QGIS projects
**Use Case**: Desktop GIS integration

### 84. `process_vector_metadata_extraction`
**Trigger**: Service Bus queue `vector-metadata-extraction`
**Purpose**: Extract vector metadata (OGR)
**Action**: Read Shapefile/GPKG schema, CRS, extent
**Use Case**: Vector ETL step 1

### 85. `process_vector_load_to_postgis`
**Trigger**: Service Bus queue `vector-load-to-postgis`
**Purpose**: Load vector data into PostGIS
**Action**: OGR2OGR import with spatial indexing
**Use Case**: Vector ETL step 2

---

## Function Count by Category

| Category | Count | Purpose |
|----------|-------|---------|
| Database Admin | 17 | PostgreSQL introspection, debugging, maintenance |
| Service Bus Admin | 6 | Queue monitoring, message inspection |
| CoreMachine (Jobs/Tasks) | 7 | Background job orchestration |
| STAC API | 16 | Spatiotemporal metadata catalog (standards-compliant) |
| OGC Features | 7 | Vector feature access (standards-compliant) |
| Platform Layer | 9 | High-level data ingestion orchestration |
| H3 Grid System | 11 | Global hexagonal geospatial indexing |
| DDH Integration | 1 | External system integration |
| Service Bus Processors | 9 | Background workers (not HTTP) |
| System Health | 1 | Application monitoring |
| **TOTAL** | **80** | |

---

## API Design Patterns

### Standards-Compliant APIs
- **STAC API**: Full STAC v1.0 compliance (landing, conformance, collections, search, transactions)
- **OGC Features**: OGC API - Features Core 1.0 compliance (landing, conformance, collections, items, bbox filtering)

### Admin Endpoints
- **Database**: `/api/dbadmin/*` - PostgreSQL introspection (no DBeaver needed)
- **Service Bus**: `/api/servicebus/admin/*` - Queue monitoring and management
- **Debugging**: `/api/db/*` - CoreMachine/Platform debugging without database access

### Nuclear Options (DEV/TEST ONLY)
- `/api/db/schema/nuke` - Drop all schemas
- `/api/db/schema/redeploy` - Nuke + redeploy
- `/api/stac/nuke` - Clear STAC catalog
- `/api/servicebus/admin/queues/{queue}/nuke` - Purge queue messages

All nuclear endpoints require `?confirm=yes` query parameter.

---

## Architecture Notes

### Two-Layer Architecture (26 OCT 2025)
1. **Platform Layer** (platform schema): High-level API requests, orchestration jobs
2. **CoreMachine Layer** (app schema): Low-level job/task execution

### Three Standards-Compliant APIs (30 OCT 2025)
1. **STAC API** - Metadata search and discovery
2. **OGC Features API** - Vector feature access
3. **Platform/CoreMachine** - Custom data processing

### Service Bus Integration
- **HTTP Triggers** (23 functions): User-facing API endpoints
- **Service Bus Triggers** (9 functions): Background processing
- **Total Triggers** (32 functions): 23 HTTP + 9 Service Bus

### Background Worker Pattern
HTTP submission → Service Bus queue → Background processor → Database update → Status query

---

## Testing Endpoints

### Quick Health Checks
```bash
# Application health
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health

# Database health
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/health

# Service Bus health
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/servicebus/admin/health

# STAC API landing
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/collections

# OGC Features landing
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/features
```

### Debug Endpoints (No DBeaver Required)
```bash
# All jobs and tasks
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/db/debug/all?limit=100

# Failed jobs
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/db/jobs?status=failed

# Running queries
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/queries/running

# Queue status
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/servicebus/admin/queues
```

---

**Last Updated**: 13 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Function App**: rmhazuregeoapi (B3 Basic tier)
