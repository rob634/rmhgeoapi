# STAC as Metadata Bridge Between DDH and Geospatial API

**Date**: 13 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: FUTURE FEATURE - Architecture documented for later implementation

---

## Executive Summary

STAC (SpatioTemporal Asset Catalog) will serve as the **metadata bridge** between the external Data & Dashboards Hub (DDH) application and our geospatial processing pipeline. While OGC Features API handles spatial queries, STAC provides the critical layer for:

1. **Bidirectional linking** between DDH resources and PostGIS tables
2. **Provenance tracking** for ETL pipeline outputs
3. **Metadata synchronization** between systems
4. **Non-functional metadata** management (source files, processing parameters, DDH foreign keys)

---

## Architecture Decision: STAC + OGC Features (Complementary, Not Competing)

### STAC = Catalog/Discovery/Metadata Bridge
**Purpose**: Link DDH metadata to geospatial data, track provenance, enable cross-system queries

**Use for**:
- Raster assets (COGs)
- GeoParquet exports
- Vector analysis results derived from rasters
- **All data ingested via Platform API** (from DDH)

### OGC Features = Data Access/Spatial Queries
**Purpose**: Direct spatial queries, real-time filtering, vector feature access

**Use for**:
- Direct PostGIS queries
- Spatial filtering (bbox, attribute queries)
- GIS tool integration
- Vector feature visualization

---

## The Critical Flow: DDH → Platform API → ETL → STAC Registration

### 1. Platform Request from DDH
```json
POST /api/platform/submit
{
  "dataset_id": "acled-2024",              // DDH's dataset identifier
  "resource_id": "somalia-events",         // DDH's resource identifier
  "version_id": "v2",                      // DDH's version tracking
  "data_type": "vector",                   // or "raster"
  "source_location": "https://.../acled_2024_somalia.csv",
  "parameters": {
    "file_extension": "csv",
    "lat_name": "latitude",
    "lon_name": "longitude"
  },
  "client_id": "ddh"
}
```

### 2. Vector ETL Pipeline Executes
```
Platform Orchestrator
  ↓
CoreMachine Job: ingest_vector
  ↓
Tasks: validate, chunk, load to PostGIS
  ↓
PostGIS Table Created: geo.acled_somalia_2024
```

### 3. STAC Registration (THE BRIDGE!)
```json
POST /api/stac/vector
{
  "schema": "geo",
  "table_name": "acled_somalia_2024",
  "collection_id": "vectors",
  "source_file": "acled_2024_somalia.csv",
  "insert": true,
  "properties": {
    // DDH Integration Metadata (CRITICAL!)
    "ddh:dataset_id": "acled-2024",
    "ddh:resource_id": "somalia-events",
    "ddh:version_id": "v2",
    "ddh:foreign_key": "ddh_resource_12345",

    // ETL Provenance
    "etl:job_id": "job_abc123",
    "etl:platform_request_id": "request_xyz789",
    "etl:timestamp": "2025-11-13T22:45:00Z",
    "etl:pipeline": "vector_ingest",
    "etl:parameters": {
      "chunk_size": 5000,
      "lat_name": "latitude",
      "lon_name": "longitude"
    }
  }
}
```

### 4. STAC Item Structure (Complete Example)
```json
{
  "type": "Feature",
  "stac_version": "1.0.0",
  "id": "acled_somalia_2024",
  "collection": "vectors",
  "geometry": {
    "type": "Polygon",
    "coordinates": [[...]]
  },
  "bbox": [40.98, -1.68, 51.41, 12.02],

  "properties": {
    // Geospatial Metadata
    "datetime": "2025-11-13T00:00:00Z",
    "proj:epsg": 4326,
    "table:row_count": 1234,

    // DDH INTEGRATION (The Bridge!)
    "ddh:dataset_id": "acled-2024",
    "ddh:resource_id": "somalia-events",
    "ddh:version_id": "v2",
    "ddh:foreign_key": "ddh_resource_12345",

    // ETL Provenance
    "etl:job_id": "job_abc123",
    "etl:platform_request_id": "request_xyz789",
    "etl:timestamp": "2025-11-13T22:45:00Z",
    "etl:pipeline": "vector_ingest",
    "etl:source_file": "acled_2024_somalia.csv",
    "etl:parameters": {
      "chunk_size": 5000,
      "lat_name": "latitude",
      "lon_name": "longitude"
    },

    // QA Status (Future)
    "qa:status": "pending",
    "qa:reviewed_by": null,
    "qa:reviewed_at": null
  },

  "assets": {
    "postgis": {
      "href": "postgresql://rmhpgflex.postgres.database.azure.com/geo.acled_somalia_2024",
      "type": "application/vnd.postgresql",
      "roles": ["data"],
      "title": "PostGIS table"
    },
    "ogc_features": {
      "href": "https://rmhazuregeoapi-.../api/features/collections/acled_somalia_2024/items",
      "type": "application/geo+json",
      "roles": ["data"],
      "title": "OGC Features API endpoint"
    },
    "preview": {
      "href": "https://rmhazuregeo.z13.web.core.windows.net/?collection=acled_somalia_2024",
      "type": "text/html",
      "roles": ["overview"],
      "title": "Interactive map preview"
    }
  },

  "links": [
    {
      "rel": "self",
      "href": "https://rmhazuregeoapi-.../api/stac/collections/vectors/items/acled_somalia_2024"
    },
    {
      "rel": "parent",
      "href": "https://rmhazuregeoapi-.../api/stac/collections/vectors"
    },
    {
      "rel": "collection",
      "href": "https://rmhazuregeoapi-.../api/stac/collections/vectors"
    },
    {
      "rel": "source",
      "href": "https://ddh.example.com/datasets/acled-2024/resources/somalia-events",
      "title": "DDH Source Resource"
    }
  ]
}
```

---

## Benefits of This Architecture

### ✅ Bidirectional Linking
```
DDH Resource ←→ STAC Item ←→ PostGIS Table
     ↓              ↓              ↓
  Metadata    Bridge Layer    Spatial Data
```

**DDH → Your System**:
- DDH stores STAC item ID (returned in Platform API response)
- DDH can query STAC API to get geospatial extent, feature counts
- DDH can link to OGC Features viewer for preview
- DDH can track processing status via STAC properties

**Your System → DDH**:
- STAC properties store DDH foreign keys (`ddh:resource_id`)
- Query: "What DDH resource does this PostGIS table belong to?"
- Audit trail: "This table came from DDH request XYZ"
- Reprocessing: Find all resources from specific DDH dataset

### ✅ Metadata Synchronization

**Scenario 1: DDH Updates Version**
```sql
-- Find STAC item by DDH resource ID
SELECT * FROM pgstac.items
WHERE properties->>'ddh:resource_id' = 'somalia-events';

-- Update STAC item version
UPDATE pgstac.items
SET properties = jsonb_set(properties, '{ddh:version_id}', '"v3"')
WHERE properties->>'ddh:resource_id' = 'somalia-events';
```

**Scenario 2: Reprocessing Request**
```python
# DDH sends reprocessing request for resource
request = {
    "dataset_id": "acled-2024",
    "resource_id": "somalia-events",
    "version_id": "v3",  # New version
    "source_location": "https://.../acled_2024_somalia_v3.csv"
}

# Platform finds existing STAC items
existing = stac_search(query={"ddh:resource_id": "somalia-events"})

# Mark old version as superseded
update_stac_item(existing[0].id, properties={"qa:status": "superseded"})

# New ETL creates new STAC item with v3
```

### ✅ Provenance Tracking

**Query Examples**:
```sql
-- Which PostGIS tables came from DDH in the last week?
SELECT
    properties->>'ddh:dataset_id' as dataset,
    properties->>'ddh:resource_id' as resource,
    content->>'id' as table_name,
    properties->>'etl:timestamp' as created
FROM pgstac.items
WHERE properties->>'etl:timestamp' > NOW() - INTERVAL '7 days'
  AND properties ? 'ddh:dataset_id'
ORDER BY created DESC;

-- What was the source file for this PostGIS table?
SELECT properties->>'etl:source_file'
FROM pgstac.items
WHERE content->>'id' = 'acled_somalia_2024';

-- Which ETL job created this data?
SELECT
    properties->>'etl:job_id',
    properties->>'etl:platform_request_id',
    properties->>'etl:parameters'
FROM pgstac.items
WHERE content->>'id' = 'acled_somalia_2024';

-- All resources from a specific DDH dataset
SELECT content->>'id', properties->>'ddh:resource_id'
FROM pgstac.items
WHERE properties->>'ddh:dataset_id' = 'acled-2024';
```

### ✅ Data Curator QA Workflow

**Current State** (OGC Features only):
1. ETL completes → PostGIS table created
2. Curator opens $web map viewer
3. Selects collection from dropdown
4. Validates geometry looks correct
5. ❌ **No way to know**: What file? Which DDH resource? Which job?

**Future State** (with STAC bridge):
1. ETL completes → PostGIS table + STAC item created
2. Curator receives notification with viewer link:
   ```
   https://rmhazuregeoapi-.../api/vector/viewer?collection=acled_somalia_2024
   ```
3. Viewer shows metadata panel:
   - **DDH Dataset**: acled-2024 (link to DDH)
   - **DDH Resource**: somalia-events (link to DDH)
   - **DDH Version**: v2
   - **Source File**: acled_2024_somalia.csv
   - **ETL Job**: job_abc123 (link to job status)
   - **Feature Count**: 1,234
   - **Bounding Box**: [40.98, -1.68, 51.41, 12.02]
4. Validates geometry looks correct
5. Approves or marks for reprocessing:
   ```python
   # Update STAC item QA status
   PATCH /api/stac/collections/vectors/items/acled_somalia_2024
   {
     "properties": {
       "qa:status": "approved",
       "qa:reviewed_by": "curator@example.com",
       "qa:reviewed_at": "2025-11-13T23:00:00Z"
     }
   }
   ```
6. DDH queries STAC to check QA status

---

## Implementation Roadmap

### Phase 1: Auto-Register STAC Items (Platform Orchestrator)

**Modify**: `triggers/trigger_platform.py` - `PlatformOrchestrator`

```python
def _handle_job_completion(self, job_id: str, job_type: str, status: str, result: dict):
    """Handle CoreMachine job completion."""

    # Find platform request
    request = self.request_repo.get_by_job_id(job_id)

    if status == "completed" and job_type == "ingest_vector":
        # Auto-register in STAC
        stac_properties = {
            # DDH Integration
            "ddh:dataset_id": request.dataset_id,
            "ddh:resource_id": request.resource_id,
            "ddh:version_id": request.version_id,
            "ddh:request_id": request.request_id,

            # ETL Provenance
            "etl:job_id": job_id,
            "etl:platform_request_id": request.request_id,
            "etl:timestamp": datetime.now(timezone.utc).isoformat(),
            "etl:pipeline": "vector_ingest",
            "etl:source_file": request.source_location,
            "etl:parameters": result.get("parameters", {})
        }

        # Register in STAC
        from infrastructure.stac import register_vector_in_stac
        stac_result = register_vector_in_stac(
            schema="geo",
            table_name=result["table_name"],
            collection_id="vectors",
            source_file=request.source_location,
            properties=stac_properties
        )

        # Update platform request with STAC item ID
        self.request_repo.update_metadata(
            request.request_id,
            {"stac_item_id": stac_result["stac_item_id"]}
        )

        logger.info(f"STAC item created: {stac_result['stac_item_id']}")
```

### Phase 2: Enhance Vector Viewer

**Create**: New viewer at `/api/vector/viewer?collection={table_name}`

Uses OGC Features API for geometry + STAC API for metadata:
1. Query OGC Features for geometry: `/api/features/collections/{id}`
2. Query STAC for metadata: `/api/stac/search?query={"id": "{table_name}"}`
3. Display both in viewer

### Phase 3: DDH Integration Endpoints

**New Endpoints**:
```python
# DDH queries "what did you create for my resource?"
GET /api/platform/resources/{resource_id}/stac
# Returns: STAC item(s) with DDH metadata

# DDH queries "what's the status of my data?"
GET /api/platform/resources/{resource_id}/status
# Returns: ETL status + QA status from STAC properties

# DDH updates metadata in STAC
PATCH /api/platform/resources/{resource_id}/metadata
{
  "version_id": "v3",
  "custom_metadata": {...}
}
```

### Phase 4: QA Workflow Integration

**New Endpoints**:
```python
# Curator approves data
POST /api/qa/approve/{stac_item_id}
{
  "reviewed_by": "curator@example.com",
  "notes": "Geometry validated, feature count matches source"
}
# Updates STAC properties: qa:status = "approved"

# Curator marks for reprocessing
POST /api/qa/reject/{stac_item_id}
{
  "reviewed_by": "curator@example.com",
  "reason": "Missing features in southern region",
  "notes": "Chunk size too large, retry with chunk_size=1000"
}
# Updates STAC properties: qa:status = "rejected"
# Triggers reprocessing job
```

---

## Industry Patterns (Validation)

### Microsoft Planetary Computer
```
STAC API → Satellite imagery catalog with rich metadata
PostGIS → Vector reference data (admin boundaries)
Separate systems, STAC links to external data sources via assets
```

### Element84 Earth Search
```
STAC API → Discovery and metadata (300+ million items)
External data access → S3, PostGIS, etc. (linked via assets)
STAC properties store processing provenance
```

### AWS Open Data
```
STAC → Discovery of datasets with provenance
Direct access → S3/PostGIS/etc. (STAC assets point to data)
Properties track data lineage and processing
```

**Pattern**: STAC as metadata layer, not data storage layer

---

## Key Design Principles

1. **STAC is the Bridge, Not the Source**
   - PostGIS stores actual vector data
   - STAC stores metadata + references to PostGIS
   - OGC Features API provides spatial query interface

2. **Automatic Registration**
   - Platform Orchestrator auto-creates STAC items on job completion
   - No manual STAC registration for Platform API requests
   - Direct ETL requests (non-Platform) may skip STAC registration

3. **Bidirectional Linking**
   - STAC → DDH: Properties contain `ddh:resource_id`, `ddh:dataset_id`
   - DDH → STAC: Platform API response returns `stac_item_id`
   - Platform database: `orchestration_jobs` table stores `stac_item_id`

4. **Provenance First**
   - Every STAC item MUST have `etl:job_id` and `etl:timestamp`
   - Platform requests MUST have `ddh:*` properties
   - Source file tracking via `etl:source_file`

5. **QA Integration**
   - STAC properties track `qa:status`, `qa:reviewed_by`, `qa:reviewed_at`
   - DDH can query QA status before making data public
   - Rejected data triggers automatic reprocessing

---

## Future Enhancements

### STAC Search for Users (Public-Facing)
Currently STAC is internal (app functionality only). Future: Expose to users.

```python
# User searches for all data covering Somalia from 2024
POST /api/stac/search
{
  "bbox": [40.98, -1.68, 51.41, 12.02],  # Somalia bbox
  "datetime": "2024-01-01/2024-12-31",
  "query": {
    "ddh:dataset_id": {"eq": "acled-2024"}
  }
}

# Returns: All STAC items (vectors + rasters) matching criteria
```

### Temporal Tracking
```python
# Track data updates over time
{
  "properties": {
    "ddh:version_id": "v3",
    "temporal:supersedes": "acled_somalia_2024_v2",  # Previous version
    "temporal:superseded_by": null,  # Latest version
    "temporal:valid_from": "2024-01-01T00:00:00Z",
    "temporal:valid_to": null  # Still valid
  }
}
```

### Raster Integration
When raster COG pipeline is complete:
```python
{
  "type": "Feature",
  "id": "landsat8_somalia_20240615",
  "collection": "rasters",
  "properties": {
    "ddh:dataset_id": "landsat-8",
    "ddh:resource_id": "LC08_L1TP_044034_20210622",
    "etl:job_id": "job_raster_123",
    "etl:pipeline": "raster_to_cog"
  },
  "assets": {
    "cog": {
      "href": "https://rmhazuregeo.blob.core.windows.net/silver/landsat8_somalia_20240615.tif",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized"
    },
    "titiler": {
      "href": "https://rmhtitiler-.../cog/tiles/{z}/{x}/{y}?url=...",
      "type": "application/json",
      "roles": ["tiles"]
    }
  }
}
```

---

## Related Documentation

- **CLAUDE.md** - Main project documentation
- **PGSTAC-REGISTRATION.md** - STAC setup and pgstac schema details
- **docs_claude/COREMACHINE_PLATFORM_ARCHITECTURE.md** - Two-layer architecture overview
- **docs_claude/SERVICE_BUS_HARMONIZATION.md** - Platform API integration patterns

---

## Decision Log

**13 NOV 2025**: Architecture decision made to use STAC as metadata bridge
- **Context**: Vector data curators need to track "what file generated this PostGIS table" and "what's the DDH foreign key"
- **Decision**: STAC properties will store DDH metadata + ETL provenance
- **Rationale**: STAC is industry standard for metadata, supports rich properties, enables bidirectional linking
- **Alternative Considered**: OGC Features only (rejected - doesn't provide metadata bridge to external systems)

---

## Status: FUTURE FEATURE

This architecture is **documented but not yet implemented**. Circle back when:
1. DDH integration requirements are finalized
2. Platform API is in production use
3. Data curator QA workflow needs DDH metadata tracking

**Implementation Priority**: Medium (after Platform API stabilizes, before production rollout)

**Author**: Robert and Geospatial Claude Legion
**Date**: 13 NOV 2025