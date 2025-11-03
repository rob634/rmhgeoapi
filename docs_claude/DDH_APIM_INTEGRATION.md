# DDH APIM Integration - Parameter Mapping

**Date**: 1 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Define APIM transformation layer for DDH API v1 → Platform Service integration

---

## 🎯 Integration Overview

**DDH (Data Distribution Hub)** submits requests via APIM to Platform Service.
APIM transforms DDH API v1 format to Platform internal format.

```
DDH Application
    ↓ (DDH API v1 format)
Azure API Management (APIM)
    ↓ (Transform to Platform format)
Platform Service (/api/platform/submit)
    ↓ (Create CoreMachine jobs)
CoreMachine (Job→Stage→Task execution)
    ↓ (Return data access URLs)
DDH Application (receives OGC/STAC endpoints)
```

---

## 📊 Parameter Mapping Table

### Core Parameters (All Operations)

| DDH Parameter | Type | Platform Mapping | Implementation | Notes |
|--------------|------|------------------|----------------|-------|
| `containerName` | string | `parameters.container_name` | ✅ Immediate | Azure storage container (bronze-vectors, bronze-rasters) |
| `operation` | string | `parameters.operation` | ✅ Immediate | CREATE, UPDATE, DELETE - Platform determines job type |
| `fileName` | string/array | `parameters.file_name` | ✅ Immediate | Single file or array for raster collections |
| `datasetId` | string | `dataset_id` | ✅ Exists | DDH dataset identifier |
| `resourceId` | string | `resource_id` | ✅ Exists | DDH resource identifier |
| `versionId` | string | `version_id` | ✅ Exists | DDH version identifier |
| `serviceName` | string | `metadata.service_name` | ✅ Immediate | Maps to STAC item_id |
| `accessLevel` | string | `metadata.access_level` | ✅ Immediate | public/OUO/restricted - capture now, enforce later |
| `description` | string | `metadata.description` | ✅ Immediate | Service description for API/STAC |
| `tags` | array | `metadata.tags` | ✅ Immediate | Tags for categorization/search |

### Vector Processing Options

| DDH Parameter | Type | Platform Mapping | Implementation |
|--------------|------|------------------|----------------|
| `processingOptions.timeIndex` | string/array | `parameters.processing_options.time_index` | ⏳ Phase 2 |
| `processingOptions.attributeIndex` | string/array | `parameters.processing_options.attribute_index` | ⏳ Phase 2 |
| `processingOptions.overwrite` | bool | `parameters.processing_options.overwrite` | ✅ Immediate |
| `processingOptions.coordinateMapping.lonColumn` | string | `parameters.processing_options.lon_column` | ✅ Immediate |
| `processingOptions.coordinateMapping.latColumn` | string | `parameters.processing_options.lat_column` | ✅ Immediate |
| `processingOptions.coordinateMapping.wktColumn` | string | `parameters.processing_options.wkt_column` | ✅ Immediate |

### Raster Processing Options

| DDH Parameter | Type | Platform Mapping | Implementation |
|--------------|------|------------------|----------------|
| `processingOptions.rasterOptions.crs` | integer | `parameters.processing_options.crs` | ✅ Immediate |
| `processingOptions.rasterOptions.noDataValue` | integer | `parameters.processing_options.nodata_value` | ✅ Immediate |
| `processingOptions.rasterOptions.bandDescriptions` | json | `parameters.processing_options.band_descriptions` | ⏳ Phase 2 |
| `processingOptions.rasterOptions.rasterCollection` | string | `parameters.processing_options.raster_collection` | ⏳ Phase 2 |
| `processingOptions.rasterOptions.temporalOrder` | json | `parameters.processing_options.temporal_order` | ⏳ Phase 2 |

### Styling Options (All Types)

| DDH Parameter | Type | Platform Mapping | Implementation |
|--------------|------|------------------|----------------|
| `processingOptions.styling.type` | string | `parameters.styling.type` | ⏳ Phase 2 |
| `processingOptions.styling.property` | string | `parameters.styling.property` | ⏳ Phase 2 |
| `processingOptions.styling.colorRamp` | string/array | `parameters.styling.color_ramp` | ⏳ Phase 2 |
| `processingOptions.styling.classification` | string | `parameters.styling.classification` | ⏳ Phase 2 |
| `processingOptions.styling.classes` | int | `parameters.styling.classes` | ⏳ Phase 2 |

---

## 🔄 Operation → Job Type Mapping

Platform determines CoreMachine jobs based on **operation** + **data_type**:

### CREATE Operations

| Data Type | DDH Operation | Platform Behavior | CoreMachine Jobs Created |
|-----------|--------------|-------------------|-------------------------|
| Vector | CREATE | Ingest new vector data | 1. `ingest_vector`<br>2. `stac_catalog_vectors` (chained) |
| Raster | CREATE | Process and create COG | 1. `validate_raster_job`<br>2. `process_raster` (COG creation) |
| Raster Collection | CREATE | Process multiple rasters | 1. `validate_raster_job` (per file)<br>2. `process_raster_collection` |

### UPDATE Operations

| Data Type | DDH Operation | Platform Behavior | CoreMachine Jobs Created |
|-----------|--------------|-------------------|-------------------------|
| Vector | UPDATE | Replace existing service | 1. `ingest_vector` (with overwrite=true)<br>2. `stac_catalog_vectors` (update metadata) |
| Raster | UPDATE | Replace existing COG | 1. `validate_raster_job`<br>2. `process_raster` (overwrite existing) |

### DELETE Operations

| Data Type | DDH Operation | Platform Behavior | CoreMachine Jobs Created |
|-----------|--------------|-------------------|-------------------------|
| Vector | DELETE | Remove from PostGIS + STAC | 1. `delete_vector_service` (future job) |
| Raster | DELETE | Remove COG + STAC | 1. `delete_raster_service` (future job) |

**Note**: DELETE jobs not yet implemented - Phase 2 feature.

---

## 📝 Request Transformation Examples

### Example 1: DDH Vector CREATE Request

**DDH Request (APIM Input):**
```json
{
  "containerName": "bronze-vectors",
  "operation": "CREATE",
  "fileName": "parcels_kingcounty.geojson",
  "datasetId": "king-county-parcels",
  "resourceId": "parcels-2024",
  "versionId": "v1.0",
  "serviceName": "King County Parcels 2024",
  "accessLevel": "public",
  "description": "Property parcel boundaries for King County, Washington",
  "tags": ["parcels", "king-county", "2024"],
  "processingOptions": {
    "overwrite": false,
    "attributeIndex": ["parcel_id", "owner_name"],
    "timeIndex": "update_date"
  }
}
```

**Platform Request (APIM Output):**
```json
{
  "dataset_id": "king-county-parcels",
  "resource_id": "parcels-2024",
  "version_id": "v1.0",
  "data_type": "vector",
  "source_location": "https://rmhazuregeo.blob.core.windows.net/bronze-vectors/parcels_kingcounty.geojson",
  "parameters": {
    "container_name": "bronze-vectors",
    "operation": "CREATE",
    "file_name": "parcels_kingcounty.geojson",
    "processing_options": {
      "overwrite": false,
      "attribute_index": ["parcel_id", "owner_name"],
      "time_index": "update_date"
    }
  },
  "metadata": {
    "service_name": "King County Parcels 2024",
    "access_level": "public",
    "description": "Property parcel boundaries for King County, Washington",
    "tags": ["parcels", "king-county", "2024"]
  },
  "client_id": "ddh"
}
```

**Platform Orchestration:**
1. Determine data_type from file extension (.geojson → vector)
2. Determine jobs from operation (CREATE) + data_type (vector)
3. Create jobs:
   - `ingest_vector` (table_name: `king_county_parcels_parcels_2024`)
   - `stac_catalog_vectors` (item_id: `King County Parcels 2024`)

**DDH Response:**
```json
{
  "success": true,
  "request_id": "a1b2c3d4e5f6...",
  "status": "processing",
  "jobs_created": ["job_abc123...", "job_def456..."],
  "message": "Platform request submitted. 2 jobs created.",
  "monitor_url": "/api/platform/status/a1b2c3d4e5f6..."
}
```

### Example 2: DDH Raster CREATE Request

**DDH Request (APIM Input):**
```json
{
  "containerName": "bronze-rasters",
  "operation": "CREATE",
  "fileName": "landsat8_scene.tif",
  "datasetId": "landsat-8",
  "resourceId": "LC08_L1TP_044034_20210622",
  "versionId": "v1.0",
  "serviceName": "Landsat 8 Scene - June 2021",
  "accessLevel": "public",
  "description": "Landsat 8 surface reflectance imagery",
  "tags": ["landsat", "2021", "multispectral"],
  "processingOptions": {
    "rasterOptions": {
      "crs": 4326,
      "noDataValue": 0,
      "bandDescriptions": {
        "1": "Coastal Aerosol",
        "2": "Blue",
        "3": "Green",
        "4": "Red",
        "5": "NIR"
      }
    },
    "styling": {
      "type": "stretch",
      "colorRamp": "viridis"
    }
  }
}
```

**Platform Request (APIM Output):**
```json
{
  "dataset_id": "landsat-8",
  "resource_id": "LC08_L1TP_044034_20210622",
  "version_id": "v1.0",
  "data_type": "raster",
  "source_location": "https://rmhazuregeo.blob.core.windows.net/bronze-rasters/landsat8_scene.tif",
  "parameters": {
    "container_name": "bronze-rasters",
    "operation": "CREATE",
    "file_name": "landsat8_scene.tif",
    "processing_options": {
      "crs": 4326,
      "nodata_value": 0,
      "band_descriptions": {
        "1": "Coastal Aerosol",
        "2": "Blue",
        "3": "Green",
        "4": "Red",
        "5": "NIR"
      }
    },
    "styling": {
      "type": "stretch",
      "color_ramp": "viridis"
    }
  },
  "metadata": {
    "service_name": "Landsat 8 Scene - June 2021",
    "access_level": "public",
    "description": "Landsat 8 surface reflectance imagery",
    "tags": ["landsat", "2021", "multispectral"]
  },
  "client_id": "ddh"
}
```

**Platform Orchestration:**
1. Determine data_type from file extension (.tif → raster)
2. Determine jobs from operation (CREATE) + data_type (raster)
3. Create jobs:
   - `validate_raster_job` (check CRS, bounds, etc.)
   - `process_raster` (create COG with band metadata)

---

## 🔧 Data Type Detection Logic

Platform determines `data_type` from `fileName` extension:

```python
def detect_data_type(file_name: str) -> str:
    """Detect data type from file extension"""
    ext = file_name.lower().split('.')[-1]

    # Vector formats
    if ext in ['geojson', 'gpkg', 'shp', 'zip', 'csv']:
        return 'vector'

    # Raster formats
    elif ext in ['tif', 'tiff', 'img', 'hdf', 'nc']:
        return 'raster'

    # Point cloud formats
    elif ext in ['las', 'laz', 'e57']:
        return 'pointcloud'

    # 3D mesh formats
    elif ext in ['obj', 'fbx', 'gltf', 'glb']:
        return 'mesh_3d'

    # Tabular formats
    elif ext in ['xlsx', 'parquet']:
        return 'tabular'

    else:
        raise ValueError(f"Unsupported file format: {ext}")
```

---

## 🎯 serviceName → STAC item_id Mapping

**DDH Provides:**
- `serviceName`: "King County Parcels 2024" (human-readable)

**Platform Maps To:**
- STAC `item_id`: Sanitized version for URL-safe identifiers
- STAC `title`: Original serviceName (preserved)

**Sanitization Logic:**
```python
def sanitize_item_id(service_name: str) -> str:
    """Convert service name to URL-safe STAC item_id"""
    # Lowercase, replace spaces with hyphens, remove special chars
    item_id = service_name.lower()
    item_id = item_id.replace(' ', '-')
    item_id = re.sub(r'[^a-z0-9\-_]', '', item_id)
    return item_id

# Example:
# "King County Parcels 2024" → "king-county-parcels-2024"
```

**STAC Metadata:**
```json
{
  "id": "king-county-parcels-2024",
  "title": "King County Parcels 2024",
  "description": "Property parcel boundaries for King County, Washington",
  "keywords": ["parcels", "king-county", "2024"]
}
```

---

## 🔒 accessLevel Capture (Implementation Later)

**Current Behavior:**
- Platform captures `access_level` in `metadata.access_level`
- No enforcement yet - stored for future use

**Future Implementation (Phase 2):**
- `public`: No authentication required (OGC/STAC endpoints open)
- `OUO`: Requires authentication (Azure AD integration)
- `restricted`: Requires authorization (role-based access control)

**Storage:**
```python
# Stored in ApiRequest.metadata
{
  "access_level": "public",  # public | OUO | restricted
  "service_name": "King County Parcels 2024",
  "description": "...",
  "tags": [...]
}
```

---

## 📋 Implementation Checklist

### Phase 1: Immediate (APIM + Platform Updates)

- [ ] **Update Platform Models** (`core/models/platform.py`)
  - [ ] Add validation for `operation` field (CREATE/UPDATE/DELETE)
  - [ ] Add `metadata` fields for serviceName, accessLevel, description, tags
  - [ ] Add `parameters` fields for container_name, file_name, processing_options

- [ ] **Update PlatformOrchestrator** (`triggers/trigger_platform.py`)
  - [ ] Implement data_type detection from fileName
  - [ ] Implement operation → job type mapping logic
  - [ ] Pass serviceName to STAC jobs as item_id
  - [ ] Construct source_location from containerName + fileName

- [ ] **Create APIM Policy** (Azure Portal)
  - [ ] Define DDH API v1 → Platform transformation
  - [ ] Test with sample requests

- [ ] **Update Documentation**
  - [ ] Document DDH integration in ARCHITECTURE_REFERENCE.md
  - [ ] Create API examples for DDH developers

### Phase 2: Advanced Features (Later)

- [ ] Implement DELETE operations (`delete_vector_service`, `delete_raster_service` jobs)
- [ ] Implement access_level enforcement (Azure AD integration)
- [ ] Implement advanced styling options (pass to rendering layer)
- [ ] Implement temporal/attribute indexing for vectors
- [ ] Implement raster collection support (array of fileNames)

---

## 🚀 Testing Strategy

### Test Case 1: Vector CREATE
```bash
# DDH submits via APIM
curl -X POST https://rmhazureapim.azure-api.net/ddh/v1/submit \
  -H "Content-Type: application/json" \
  -d @test_vector_create.json

# Expected: Platform creates ingest_vector + stac_catalog_vectors jobs
```

### Test Case 2: Raster CREATE
```bash
# DDH submits via APIM
curl -X POST https://rmhazureapim.azure-api.net/ddh/v1/submit \
  -H "Content-Type: application/json" \
  -d @test_raster_create.json

# Expected: Platform creates validate_raster_job + process_raster jobs
```

### Test Case 3: Vector UPDATE
```bash
# DDH submits UPDATE operation
curl -X POST https://rmhazureapim.azure-api.net/ddh/v1/submit \
  -H "Content-Type: application/json" \
  -d @test_vector_update.json

# Expected: Platform creates ingest_vector job with overwrite=true
```

---

## 📚 Related Documentation

- **CLAUDE_CONTEXT.md** - Platform architecture overview
- **COREMACHINE_PLATFORM_ARCHITECTURE.md** - Two-layer architecture design
- **core/models/platform.py** - Platform data models
- **triggers/trigger_platform.py** - Platform orchestration logic
- **infrastructure/platform.py** - Platform repository implementation

---

**Document Status**: ✅ DRAFT - Ready for Implementation
**Last Updated**: 1 NOV 2025
**Next Steps**: Update Platform models and orchestrator to support DDH parameters
