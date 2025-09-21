# STAC Implementation Research & Architecture Design

**Date**: 14 SEP 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Research PostgreSQL STAC libraries and Python implementations for integration with our Job→Stage→Task architecture

## Executive Summary

This document outlines a comprehensive STAC (SpatioTemporal Asset Catalog) implementation strategy leveraging PgSTAC for PostgreSQL storage and PySTAC for Python operations, integrated with our existing Azure Functions-based Job→Stage→Task orchestration system.

## 🔍 Research Findings

### PgSTAC - PostgreSQL STAC Extension

**Latest Version**: 6.0.0 (August 8, 2025)
**Repository**: https://github.com/stac-utils/pgstac
**Documentation**: https://stac-utils.github.io/pgstac/

#### Key Features
- **Production Scale**: Handles hundreds of millions of STAC items
- **CQL2 Search**: Full support for complex spatial-temporal queries
- **Partitioning**: Automatic partitioning of collections and items for performance
- **Transaction Support**: Full ACID compliance with PostgreSQL
- **JSONB Storage**: Stores items exactly as received, preserving custom fields
- **Performance Optimized**: Particularly enhanced for datetime sorting

#### Database Architecture
```sql
-- PgSTAC uses separate schema
CREATE SCHEMA pgstac;

-- Three permission levels
pgstac_admin   -- Owns all objects, runs migrations
pgstac_ingest  -- Read/write for data ingestion
pgstac_read    -- Read-only access to items/collections
```

#### Recent Updates (2024-2025)
- v6.0.0 (Aug 8, 2025) - Latest major release
- v5.0.3 (Jul 23, 2025) - Performance improvements
- v5.0.0 (Mar 10, 2025) - Major API enhancements
- v4.0.0 (Feb 3, 2025) - Schema optimizations

### PySTAC - Python STAC Library

**Latest Version**: 1.13.0 (April 15, 2025)
**Repository**: https://github.com/stac-utils/pystac
**Documentation**: https://pystac.readthedocs.io/

#### Key Features
- **STAC 1.0 Support**: Full compliance with specification
- **In-Memory Operations**: Efficient catalog manipulations
- **Rasterio Integration**: Seamless metadata extraction from rasters
- **Multiple Publishing Modes**: Absolute, relative, and self-contained catalogs
- **Python 3.10-3.13**: Modern Python version support

#### Core Components
```python
import pystac
import rasterio
from pystac.extensions.projection import ProjectionExtension
from pystac.extensions.eo import EOExtension
```

### stac-fastapi-pgstac - HTTP API Layer

**Latest Version**: 6.0.0 (August 8, 2025)
**Repository**: https://github.com/stac-utils/stac-fastapi-pgstac

#### Key Features
- **FastAPI Based**: Modern async Python web framework
- **Request Validation**: Automatic input validation
- **Link Generation**: Adds appropriate links to responses
- **Transaction Extension**: Support for STAC Transaction API
- **Serverless Support**: AWS Lambda deployment (Azure Functions possible)

## 🏗️ Proposed Architecture

### Integration with Our Job→Stage→Task System

```
┌─────────────────────────────────────────────────────────┐
│                   Azure Functions App                     │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  ┌──────────────────┐        ┌──────────────────┐      │
│  │  STAC Controllers │        │  STAC Services   │      │
│  ├──────────────────┤        ├──────────────────┤      │
│  │ IngestController │───────▶│ IngestService    │      │
│  │ CatalogController│        │ CatalogService   │      │
│  │ SearchController │        │ SearchService    │      │
│  └──────────────────┘        └──────────────────┘      │
│           │                           │                  │
│           ▼                           ▼                  │
│  ┌──────────────────┐        ┌──────────────────┐      │
│  │   Job→Stage→Task │        │  STAC Repository │      │
│  │   Orchestration  │        │     (PySTAC)     │      │
│  └──────────────────┘        └──────────────────┘      │
│                                       │                  │
└───────────────────────────────────────┼──────────────────┘
                                        │
                        ┌───────────────▼──────────────┐
                        │     PostgreSQL Database      │
                        ├───────────────────────────────┤
                        │  app schema  │  pgstac schema│
                        │  (our tables)│  (STAC tables)│
                        └───────────────────────────────┘
```

### Implementation Phases

#### Phase 1: Database Setup ✅
```python
# controller_stac_setup.py
class STACSetupController(BaseController):
    """One-time STAC database setup controller"""

    def create_stage_tasks(self, stage: int, job_parameters: dict):
        if stage == 1:
            return [
                TaskDefinition(
                    task_type="install_pgstac",
                    parameters={"version": "6.0.0"}
                ),
                TaskDefinition(
                    task_type="configure_roles",
                    parameters={"roles": ["pgstac_admin", "pgstac_ingest", "pgstac_read"]}
                ),
                TaskDefinition(
                    task_type="run_migrations",
                    parameters={"schema": "pgstac"}
                )
            ]
```

#### Phase 2: STAC Ingestion Pipeline 🚀
```python
# controller_stac_ingest.py
class STACIngestController(BaseController):
    """Multi-stage STAC ingestion controller"""

    workflow = WorkflowDefinition(
        job_type="stac_ingest",
        stages=[
            StageDefinition(
                stage_number=1,
                task_type="analyze_source",
                description="Scan source container for geospatial data"
            ),
            StageDefinition(
                stage_number=2,
                task_type="extract_stac_metadata",
                description="Extract STAC metadata from files",
                max_parallel_tasks=100
            ),
            StageDefinition(
                stage_number=3,
                task_type="create_stac_items",
                description="Create STAC items in database",
                max_parallel_tasks=50
            ),
            StageDefinition(
                stage_number=4,
                task_type="update_collection",
                description="Update collection metadata"
            )
        ]
    )
```

#### Phase 3: STAC Services Implementation 🔧
```python
# service_stac.py
from typing import Dict, Any
import pystac
import rasterio
from repository_stac import STACRepository

class STACService:
    """STAC operation service handlers"""

    @staticmethod
    @TaskRegistry.register("extract_stac_metadata")
    async def extract_stac_metadata(task_context: TaskContext) -> TaskResult:
        """Extract STAC metadata from geospatial file"""
        file_path = task_context.parameters["file_path"]

        # Use rasterio to extract spatial metadata
        with rasterio.open(file_path) as src:
            bounds = src.bounds
            crs = src.crs
            transform = src.transform

        # Create STAC item
        item = pystac.Item(
            id=task_context.parameters["item_id"],
            geometry=mapping(box(*bounds)),
            bbox=list(bounds),
            datetime=datetime.utcnow(),
            properties={
                "proj:epsg": crs.to_epsg(),
                "proj:transform": list(transform),
                "eo:bands": [{"name": f"band_{i+1}"} for i in range(src.count)]
            }
        )

        return TaskResult(
            success=True,
            result_data={"stac_item": item.to_dict()}
        )
```

#### Phase 4: Repository Layer 📚
```python
# repository_stac.py
import pypgstac
from pypgstac.db import PgstacDB
from pypgstac.migrate import Migrate

class STACRepository:
    """Repository for STAC operations using PgSTAC"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        """Initialize PgSTAC connection"""
        self.db = PgstacDB(
            dsn=f"postgresql://{config.postgis_user}:{config.postgis_password}@"
                f"{config.postgis_host}:{config.postgis_port}/{config.postgis_database}"
        )

    def ingest_item(self, item: dict) -> str:
        """Ingest a STAC item into PgSTAC"""
        with self.db.connect() as conn:
            conn.execute(
                "SELECT pgstac.create_item(%s::jsonb)",
                (json.dumps(item),)
            )
        return item["id"]

    def search_items(self, search_params: dict) -> list:
        """Search STAC items using CQL2"""
        with self.db.connect() as conn:
            result = conn.execute(
                "SELECT * FROM pgstac.search(%s::jsonb)",
                (json.dumps(search_params),)
            )
            return result.fetchall()
```

### Configuration Requirements

#### Environment Variables
```bash
# Add to local.settings.json
{
  "Values": {
    "PGSTAC_SCHEMA": "pgstac",
    "PGSTAC_VERSION": "6.0.0",
    "STAC_API_VERSION": "1.0.0",
    "STAC_CATALOG_ID": "rmhazure-catalog",
    "STAC_CATALOG_TITLE": "RMH Azure Geospatial Catalog",
    "STAC_DEFAULT_COLLECTION": "bronze-tier"
  }
}
```

#### Database Permissions
```sql
-- Grant our app user access to PgSTAC
GRANT pgstac_ingest TO rob634;
GRANT USAGE ON SCHEMA pgstac TO rob634;
```

### Integration Points with Existing System

#### 1. Blob Storage → STAC
- **Trigger**: After `list_container` completes
- **Process**: Create STAC items for discovered geospatial files
- **Storage**: Items stored in `pgstac.items` table

#### 2. COG Creation → STAC Update
- **Trigger**: After COG conversion completes
- **Process**: Update STAC item with COG asset links
- **Storage**: Asset links in item properties

#### 3. STAC Search → Job Creation
- **Trigger**: STAC search results
- **Process**: Generate processing jobs for matching items
- **Output**: Job IDs for tracking

## 🚀 Implementation Roadmap

### Sprint 1: Foundation (Week 1)
- [ ] Install PgSTAC schema in database
- [ ] Create `repository_stac.py` with basic operations
- [ ] Implement `STACSetupController` for one-time setup
- [ ] Test PgSTAC functions with sample data

### Sprint 2: Ingestion (Week 2)
- [ ] Create `service_stac.py` with metadata extraction
- [ ] Implement `STACIngestController` with multi-stage workflow
- [ ] Integrate PySTAC for item creation
- [ ] Test with Bronze tier .tif files

### Sprint 3: Search & Query (Week 3)
- [ ] Implement STAC search endpoints
- [ ] Add CQL2 query support
- [ ] Create collection management endpoints
- [ ] Test performance with 1000+ items

### Sprint 4: Advanced Features (Week 4)
- [ ] Add STAC extensions (projection, eo, raster)
- [ ] Implement asset management
- [ ] Create STAC validation endpoint
- [ ] Add collection statistics

## 📊 Performance Considerations

### Expected Performance
- **Ingestion**: 100-1000 items/second
- **Search**: <100ms for spatial queries
- **Scale**: Millions of items supported

### Optimization Strategies
1. **Partitioning**: Partition by collection and datetime
2. **Indexing**: Spatial and temporal indexes on key fields
3. **Caching**: Redis for frequently accessed items
4. **Batch Operations**: Bulk insert for large ingestions

## 🔧 Testing Strategy

### Unit Tests
```python
def test_stac_item_creation():
    """Test STAC item creation from raster"""
    service = STACService()
    result = service.extract_stac_metadata({
        "file_path": "test.tif",
        "item_id": "test-item"
    })
    assert result.success
    assert "stac_item" in result.result_data
```

### Integration Tests
- Test PgSTAC installation and migration
- Verify item ingestion and retrieval
- Test search functionality
- Validate collection updates

### Performance Tests
- Ingest 10,000 items benchmark
- Search response time under load
- Concurrent user simulation

## 📚 References

### Documentation
- [STAC Specification](https://stacspec.org/)
- [PgSTAC Documentation](https://stac-utils.github.io/pgstac/)
- [PySTAC Documentation](https://pystac.readthedocs.io/)
- [STAC FastAPI](https://stac-utils.github.io/stac-fastapi/)

### Tutorials
- [Creating STAC Catalogs](https://stacspec.org/en/tutorials/)
- [PgSTAC Setup Guide](https://stac-utils.github.io/pgstac/pgstac/)
- [PySTAC Examples](https://github.com/stac-utils/pystac/tree/main/docs/tutorials)

### Community Resources
- [STAC Gitter Chat](https://gitter.im/SpatioTemporal-Asset-Catalog/Lobby)
- [STAC Utils GitHub](https://github.com/stac-utils)
- [STAC Examples](https://github.com/stac-extensions)

## 🎯 Success Metrics

1. **Database Setup**: PgSTAC schema successfully deployed
2. **Ingestion Rate**: >100 items/minute achieved
3. **Search Performance**: <200ms response time
4. **Data Integrity**: 100% of items validated against STAC spec
5. **Integration**: Seamless workflow with existing Job→Stage→Task system

## 🚨 Risk Mitigation

### Technical Risks
- **Schema Conflicts**: Use separate `pgstac` schema
- **Performance Issues**: Implement partitioning early
- **Version Compatibility**: Pin PgSTAC and PySTAC versions

### Operational Risks
- **Data Loss**: Regular backups of STAC catalog
- **Search Degradation**: Monitor query performance
- **Migration Issues**: Test migrations in dev first

---

*This research document provides the foundation for implementing a robust STAC catalog system integrated with our existing Azure Functions architecture. The phased approach ensures we can deliver value incrementally while maintaining system stability.*

# Azure Functions + PostgreSQL STAC Implementation Summary

## Architecture Decision
**Chosen approach**: Single Azure Function App with both ETL operations and STAC API endpoints, backed by PostgreSQL + PostGIS with PgSTAC extension.

**Key rationale**: 
- No Docker containers (corporate security preference)
- Database provides essential concurrency protection for parallel ETL
- PgSTAC handles STAC complexity, leaving Functions as lightweight wrappers
- Unified deployment and management

## Core Technology Stack

### Primary Libraries
```python
# Essential dependencies
pypgstac[psycopg]==0.8.5           # PgSTAC Python interface
stac-fastapi-pgstac==6.0.0         # STAC API components
pystac>=1.8.0                      # STAC object manipulation
azure-functions                    # Azure Functions runtime
azure-storage-blob                 # Blob storage integration
```

### Database
- **PostgreSQL + PostGIS + PgSTAC** on Azure Database for PostgreSQL
- PgSTAC provides production-ready STAC schema, functions, and optimizations
- Handles millions+ STAC items with automatic spatial indexing and partitioning

## Implementation Pattern

### ETL Functions (Existing Pattern Enhanced)
```python
@app.queue_trigger(arg_name="msg", queue_name="etl-queue")
def process_stac_item(msg: func.QueueMessage):
    # 1. Business logic (geospatial processing)
    processed_data = extract_geometry_from_blob(blob_data)
    
    # 2. Database operation (single call)
    stac_item = create_stac_item(item_id, processed_data)
    pypgstac.Loader(dsn).load_item(stac_item.to_dict())
```

### STAC API Functions (New Addition)
```python
@app.route(route="search", methods=["GET", "POST"])
def stac_search(req: func.HttpRequest) -> func.HttpResponse:
    # Parse standard STAC parameters
    search_params = parse_stac_search_params(req)
    
    # Execute via PgSTAC
    with pypgstac.Loader(dsn) as loader:
        result = loader.db.cursor().execute("SELECT pgstac.search(%s)", [search_params])
    
    return func.HttpResponse(json.dumps(result), mimetype="application/geo+json")
```

## Required STAC API Endpoints

### Core Endpoints to Implement
1. `GET /` - Landing page
2. `GET /collections` - List collections  
3. `GET /collections/{id}` - Get collection
4. `GET /collections/{id}/items/{id}` - Get item
5. `GET|POST /search` - Search items (main endpoint)

### Standard Query Parameters
- `bbox` - Spatial bounding box
- `datetime` - Temporal filtering  
- `collections` - Collection filtering
- `limit` - Result pagination
- `token` - Pagination token

## Database Architecture

### PgSTAC Schema
```sql
-- PgSTAC creates optimized tables automatically:
-- collections, items with spatial indexes
-- Built-in functions: pgstac.search(), pgstac.get_item(), etc.
-- Automatic extent calculation and partitioning
```

### Connection Pattern
```python
# Module-level initialization
stac_settings = Settings(
    postgres_host=os.getenv("POSTGRES_HOST"),
    postgres_dbname=os.getenv("POSTGRES_DB"),
    postgres_user=os.getenv("POSTGRES_USER"),
    postgres_pass=os.getenv("POSTGRES_PASS")
)
```

## Key Benefits

### Concurrency Protection
- PgSTAC handles race conditions automatically via database transactions
- No manual `FOR UPDATE SKIP LOCKED` or conflict resolution needed
- Built-in upsert functionality for ETL operations

### STAC Compliance  
- Native STAC JSON storage in JSONB columns
- Automatic spatial/temporal indexing
- Standard query interface that works with any STAC client

### Performance & Scalability
- Optimized for millions of STAC items
- Spatial indexes via PostGIS
- Functions auto-scale, database provides consistent performance

## Development Focus Areas

### Python Functions Handle
- **Orchestration**: Queue management, workflow coordination
- **Business Logic**: Geospatial processing, metadata extraction  
- **Integration**: Blob storage I/O, external services
- **API Routing**: HTTP request parsing, response formatting

### PgSTAC Database Handles
- **STAC Operations**: All CRUD operations on collections/items
- **Concurrency**: Transaction management, conflict resolution
- **Performance**: Query optimization, spatial indexing
- **Compliance**: STAC schema validation, extent calculations

## Implementation Notes

- Functions become **thin wrappers** around database operations
- Most STAC complexity handled by PgSTAC SQL functions
- Standard STAC clients (pystac-client, QGIS, etc.) work immediately
- No container deployment required - pure Python Function App
- ETL and API endpoints share same database connection and configuration

This architecture provides production-ready STAC capabilities with minimal custom code while leveraging Azure Functions' serverless benefits and corporate security requirements.