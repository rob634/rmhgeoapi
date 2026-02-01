# Geospatial Platform Glossary

> **Navigation**: [Quick Start](QUICK_START.md) | [Platform API](../api-reference/PLATFORM_API.md) | [Health](../api-reference/HEALTH.md) | [Errors](../api-reference/ERRORS.md) | **Glossary**

**Last Updated**: 01 FEB 2026
**Status**: Reference Documentation
**Purpose**: Clear definitions of technical terms for all team members
**Audience**: Development team (all disciplines, including ESL speakers)

---

## How to Use This Glossary

This document provides clear definitions for technical terms used throughout the platform documentation. Terms are organized alphabetically within categories.

---

## Acronyms and Abbreviations

| Acronym | Full Name | Description |
|---------|-----------|-------------|
| ACL | Anti-Corruption Layer | Design pattern that translates between external and internal data formats |
| API | Application Programming Interface | A set of rules for how software components communicate |
| bbox | Bounding Box | Rectangle defined by minimum and maximum coordinates that contains a geographic area |
| CLI | Command Line Interface | Text-based interface for running commands |
| COG | Cloud-Optimized GeoTIFF | GeoTIFF file format optimized for cloud storage access |
| CQL2 | Common Query Language 2 | OGC standard for filtering geospatial data in API queries |
| CRS | Coordinate Reference System | System that defines how coordinates map to locations on Earth |
| CSV | Comma-Separated Values | Simple text file format for tabular data |
| DDH | Development Data Hub | External application that integrates with the platform |
| DEM | Digital Elevation Model | Raster dataset representing terrain elevation |
| DLQ | Dead-Letter Queue | Queue that stores messages that could not be processed |
| EPSG | European Petroleum Survey Group | Organization that maintains coordinate system definitions (for example, EPSG:4326) |
| ESL | English as Second Language | Non-native English speakers |
| ETL | Extract, Transform, Load | Process of moving data between systems with transformation |
| FOSS | Free and Open Source Software | Software with publicly available source code |
| GDAL | Geospatial Data Abstraction Library | Library for reading and writing geospatial file formats |
| GIS | Geographic Information System | System for storing, analyzing, and visualizing geographic data |
| H3 | Hexagonal Hierarchical Spatial Index | Uber's hexagonal grid system for spatial indexing |
| HTTP | Hypertext Transfer Protocol | Protocol for transmitting data over the internet |
| JSON | JavaScript Object Notation | Lightweight data interchange format |
| MRO | Method Resolution Order | Order in which Python searches for methods in class hierarchy |
| MVP | Minimum Viable Product | Product with just enough features to be usable |
| MVT | Mapbox Vector Tiles | Binary format for encoding vector data as map tiles |
| OGC | Open Geospatial Consortium | Organization that creates geospatial standards |
| PNG | Portable Network Graphics | Image file format with lossless compression |
| REST | Representational State Transfer | Architectural style for web APIs |
| SAS | Shared Access Signature | Token that provides limited access to Azure storage |
| SDK | Software Development Kit | Collection of tools for building applications |
| SHA256 | Secure Hash Algorithm 256-bit | Algorithm that produces unique identifier from input data |
| SQL | Structured Query Language | Language for database queries |
| STAC | SpatioTemporal Asset Catalog | Standard for organizing geospatial data metadata |
| TTL | Time To Live | Duration before a message or record expires |
| URL | Uniform Resource Locator | Web address |
| UUID | Universally Unique Identifier | 128-bit number used to identify resources |
| WFS | Web Feature Service | Older OGC standard for serving vector data (replaced by OGC API - Features) |
| WGS84 | World Geodetic System 1984 | Global coordinate reference system (EPSG:4326) |
| XYZ | X, Y, Zoom | Tile coordinate system used by web maps |

---

## Architecture Terms

### CoreMachine
The internal job orchestration engine that manages the Job, Stage, and Task workflow. Power users interact with CoreMachine directly through the `/api/jobs/submit/{job_type}` endpoint.

### Platform API
The external-facing API for submitting geospatial processing jobs. Provides the `/api/platform/submit` endpoint with validation, version lineage tracking, and dry_run support.

### Platform Layer
The anti-corruption layer that sits between external applications (like DDH) and CoreMachine. It translates external identifiers to internal parameters.

### Service Layer
The unified Docker container that serves processed geospatial data through standardized APIs. Runs TiTiler, TiPG, and stac-fastapi as a single application. See [Service Layer](../architecture/SERVICE_LAYER.md).

### Docker Worker
A containerized processing environment for memory-intensive geospatial operations. **V0.8 doctrine**: The Docker Worker is PRIMARY for all vector ETL and heavy raster processing, while Azure Functions handle lightweight orchestration.

### Fan-Out Pattern
A distributed processing pattern where a single stage creates multiple parallel tasks. For example, processing 100 raster tiles creates 100 parallel COG creation tasks.

### Fan-In Pattern
A distributed processing pattern where multiple parallel tasks converge into a single aggregation task. For example, 100 COG creation tasks complete and then a single MosaicJSON task aggregates all results.

### Last Task Completion Detection Pattern
The method used to detect when all parallel tasks in a stage have completed. Uses atomic database operations to ensure exactly one task triggers the next stage.

### Early Validation Pattern
The practice of checking for errors (missing files, invalid parameters) at job submission time before any processing begins. This prevents wasted compute resources.

### dry_run
A validation mode (`?dry_run=true`) that checks all parameters and returns what would happen without actually creating a job. Useful for verifying version lineage state before submission.

### Version Lineage
Groups all versions of the same dataset/resource together. Computed as `SHA256(platform_id + dataset_id + resource_id)` excluding version_id. Enables tracking version history and ensuring proper sequencing with `previous_version_id`.

### Idempotency
The property where submitting the same request multiple times produces the same result. In this system, job IDs are SHA256 hashes of parameters, so identical submissions return the existing job.

---

## Data Storage Terms

### Bronze Container
Azure Blob Storage container for raw, unprocessed data uploaded by users. Data here has not been validated or transformed.

### Silver Container
Azure Blob Storage container for processed, validated data. Contains Cloud-Optimized GeoTIFFs (COGs) and validated vector data.

### Gold Container
Azure Blob Storage container for final exports and aggregated data. Used for GeoParquet exports and analysis-ready datasets. (Future implementation)

### Blob
A file stored in Azure Blob Storage. The term comes from "Binary Large Object".

### Zarr
A format for storing chunked, compressed N-dimensional arrays. Optimized for cloud storage and parallel access. Used for climate and weather data like ERA5.

---

## Geospatial Terms

### Bounding Box (bbox)
A rectangle that contains a geographic feature, defined by four coordinates: minimum X (west), minimum Y (south), maximum X (east), maximum Y (north). Example: `[-74.0, 40.7, -73.9, 40.8]`

### Cloud-Optimized GeoTIFF (COG)
A GeoTIFF file structured so that small portions can be read without downloading the entire file. Uses internal tiling and overviews (reduced resolution copies) for efficient cloud access.

### Coordinate Reference System (CRS)
A system that defines how map coordinates relate to real locations on Earth. Common examples:
- **EPSG:4326** (WGS84): Global latitude/longitude coordinates
- **EPSG:3857** (Web Mercator): Coordinates used by web maps

### GeoJSON
A JSON format for encoding geographic features. Contains geometry (points, lines, polygons) and properties (attributes). Widely supported by web mapping libraries.

### GeoParquet
A columnar file format for geospatial data based on Apache Parquet. Efficient for large datasets and analytical queries.

### MosaicJSON
A JSON file that indexes multiple COG files into a virtual seamless mosaic. Allows tile servers to efficiently serve tiles from multiple source files.

### Overview
A reduced-resolution copy of a raster image stored within the same file. COGs contain multiple overviews for efficient display at different zoom levels.

### PostGIS
An extension to PostgreSQL that adds support for geographic objects. Enables spatial queries like "find all points within this polygon".

### Raster
Grid-based data where each cell contains a value. Examples include satellite imagery, elevation models, and temperature maps.

### Shapefile
A common vector data format consisting of multiple files (.shp, .dbf, .shx, and others). Despite the singular name, a shapefile is actually multiple files that must be kept together.

### Tile
A small square image (typically 256x256 or 512x512 pixels) representing a portion of a map at a specific zoom level. Web maps display many tiles together to create the complete map view.

### Vector
Point, line, or polygon data with associated attributes. Examples include city locations (points), roads (lines), and country boundaries (polygons).

### Vector Tiles (MVT)
Mapbox Vector Tiles - a binary format that encodes vector data as map tiles. Enables efficient client-side rendering with styling applied in the browser.

### xarray
A Python library for working with labeled multi-dimensional arrays. Used for climate data, satellite imagery time series, and other N-dimensional datasets.

---

## Job Processing Terms

### Job
A complete unit of work submitted to the system. A job contains one or more stages that execute sequentially.

### Stage
A phase within a job. Stages execute in sequence (Stage 1 completes before Stage 2 begins). Each stage can contain multiple parallel tasks.

### Task
The smallest unit of work. Tasks within a stage execute in parallel. Each task runs a specific handler function.

### Handler
A Python function that performs the actual work for a task. Examples: `validate_raster`, `create_cog`, `upload_chunk`.

### Queue
A message storage system where work items wait to be processed. This platform uses Azure Service Bus queues:
- **geospatial-jobs**: Queue for job orchestration messages
- **geospatial-tasks**: Queue for task execution messages

### Dead-Letter Queue (DLQ)
A special queue that stores messages that could not be processed after all retry attempts. Used for debugging failed operations.

### Lock
A mechanism that prevents multiple processors from working on the same message simultaneously. Service Bus locks last 5 minutes and are automatically renewed.

### Retry
The process of attempting to execute a failed operation again. This system uses exponential backoff (waiting longer between each retry attempt).

---

## Database Terms

### Schema
A namespace within a PostgreSQL database that contains tables, functions, and other objects. This platform uses:
- **app**: Job and task records
- **geo**: User vector data
- **pgstac**: STAC metadata
- **h3**: H3 hexagonal grid data

### Advisory Lock
A PostgreSQL feature that allows code to acquire a lock on a custom identifier. Used to ensure only one task advances a job to the next stage.

### JSONB
PostgreSQL data type for storing JSON data in binary format. Allows indexing and querying of JSON fields.

---

## API and Protocol Terms

### Endpoint
A specific URL path that accepts requests. Example: `/api/platform/submit`

### OGC API - Features
A REST API standard for serving vector data. Replaces the older WFS (Web Feature Service) standard. Returns GeoJSON format.

### CQL2 (Common Query Language 2)
An OGC standard for filtering geospatial data. Supports property comparisons, spatial operations, and temporal queries. Example: `filter=area > 1000`

### STAC API
A REST API for searching and discovering geospatial datasets using STAC metadata.

### TiTiler
A dynamic tile server developed by [Development Seed](https://developmentseed.org/) that generates map tiles from COGs and Zarr datasets on request. Does not require pre-rendered tile caches. See [TiTiler Documentation](https://developmentseed.org/titiler/).

### TiPG
A PostGIS-backed OGC API server developed by [Development Seed](https://developmentseed.org/) that provides OGC API - Features and vector tile (MVT) endpoints. See [TiPG Documentation](https://developmentseed.org/tipg/).

### stac-fastapi
A STAC API implementation with pgSTAC backend for efficient spatial-temporal queries. See [stac-fastapi Documentation](https://stac-utils.github.io/stac-fastapi/).

### pgSTAC
PostgreSQL extension that stores STAC metadata and enables fast spatial and temporal queries.

---

## Azure Terms

### Function App
An Azure service that runs serverless functions. Code executes in response to triggers (HTTP requests, queue messages, timers).

### Web App for Containers
An Azure service that runs Docker containers. Used for the Service Layer and Docker Worker.

### Service Bus
Azure messaging service that provides reliable message queuing. Supports features like message locking, dead-letter queues, and scheduled delivery.

### Managed Identity
An Azure feature that allows services to authenticate to other Azure resources without storing credentials in code.

### Flexible Server
Azure PostgreSQL deployment option that provides more configuration flexibility than Single Server.

### Container Registry (ACR)
Azure Container Registry - a managed Docker registry for storing and managing container images.

---

## Development Seed Stack

The Service Layer uses open source tools from [Development Seed](https://developmentseed.org/):

| Tool | Purpose | Documentation |
|------|---------|---------------|
| **TiTiler** | Dynamic COG/Zarr tile serving | [developmentseed.org/titiler](https://developmentseed.org/titiler/) |
| **TiPG** | OGC Features API + MVT tiles | [developmentseed.org/tipg](https://developmentseed.org/tipg/) |
| **stac-fastapi** | STAC API implementation | [stac-utils.github.io/stac-fastapi](https://stac-utils.github.io/stac-fastapi/) |

---

## Pattern Names (Standardized)

The following pattern names are used consistently throughout all documentation:

| Standard Name | Previous Names (Deprecated) |
|--------------|----------------------------|
| Early Validation Pattern | Fast-fail, fail-fast |
| Last Task Completion Detection Pattern | Last task turns out the lights |
| Fan-Out Pattern | Fan-out/fan-in (when referring to parallel expansion) |
| Fan-In Pattern | Fan-out/fan-in (when referring to aggregation) |

---

## Units and Measurements

| Unit | Description | Example |
|------|-------------|---------|
| MB | Megabyte (1,000,000 bytes) | File size: 127.58 MB |
| GB | Gigabyte (1,000,000,000 bytes) | Storage capacity: 10 GB |
| ms | Milliseconds (1/1000 of a second) | Response time: 250 ms |
| PT5M | ISO 8601 duration: 5 minutes | Lock duration setting |
| P7D | ISO 8601 duration: 7 days | Message time-to-live |

---

## Common Phrases

| Phrase | Meaning |
|--------|---------|
| "at submission time" | When the job request is first received, before processing begins |
| "at request time" | When an API request is received |
| "on-the-fly" | Dynamically, as needed, without pre-computation |
| "out of the box" | Without additional configuration (use: "without additional configuration") |
| "production-proven" | Tested and reliable in real-world production systems |
| "single-pass" | Completing multiple operations in one processing step |

---

## Related Documentation

- [Quick Start](QUICK_START.md) - Getting started guide
- [Platform API](../api-reference/PLATFORM_API.md) - Job submission API
- [Service Layer](../architecture/SERVICE_LAYER.md) - Data access APIs
- [Technical Overview](../architecture/TECHNICAL_OVERVIEW.md) - System architecture

---

**Last Updated**: 01 FEB 2026
