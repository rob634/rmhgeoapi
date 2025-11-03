# DDH Platform Integration - Code Changes

**Date**: 1 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Detailed code changes for DDH integration (CREATE operation + placeholders)

---

## 📋 Overview

This document outlines changes to:
1. **Platform Models** (`core/models/platform.py`) - Add DDH parameters
2. **PlatformOrchestrator** (`triggers/trigger_platform.py`) - Add CREATE logic + placeholders

---

## 🔧 Changes to `core/models/platform.py`

### Change 1: Add Operation Enum

**Location**: After `DataType` enum (line ~80)

```python
class OperationType(str, Enum):
    """
    DDH operation types.

    Auto-generates: CREATE TYPE app.operation_type_enum AS ENUM (...)
    """
    CREATE = "CREATE"
    UPDATE = "UPDATE"  # Phase 2
    DELETE = "DELETE"  # Phase 2
```

### Change 2: Update `PlatformRequest` DTO (Incoming HTTP)

**Location**: Lines 87-114

**BEFORE:**
```python
class PlatformRequest(BaseModel):
    """Platform request from external application (DDH)."""
    dataset_id: str = Field(..., description="DDH dataset identifier")
    resource_id: str = Field(..., description="DDH resource identifier")
    version_id: str = Field(..., description="DDH version identifier")
    data_type: DataType = Field(..., description="Type of data to process")
    source_location: str = Field(..., description="Azure blob URL or path")
    parameters: Dict[str, Any] = Field(default_factory=dict)
    client_id: str = Field(..., description="Client application identifier")
```

**AFTER:**
```python
class PlatformRequest(BaseModel):
    """
    Platform request from external application (DDH).

    This is a DTO (Data Transfer Object) for incoming HTTP requests.
    Accepts DDH API v1 format and transforms to internal ApiRequest format.
    """
    # DDH Core Identifiers (Required)
    dataset_id: str = Field(..., max_length=255, description="DDH dataset identifier")
    resource_id: str = Field(..., max_length=255, description="DDH resource identifier")
    version_id: str = Field(..., max_length=50, description="DDH version identifier")

    # DDH Operation (Required)
    operation: OperationType = Field(..., description="Operation type: CREATE/UPDATE/DELETE")

    # DDH File Information (Required)
    container_name: str = Field(..., max_length=100, description="Azure storage container name (e.g., bronze-vectors)")
    file_name: Union[str, List[str]] = Field(..., description="File name(s) - single string or array for raster collections")

    # DDH Service Metadata (Required)
    service_name: str = Field(..., max_length=255, description="Human-readable service name (maps to STAC item_id)")
    access_level: str = Field(..., max_length=50, description="Data classification: public, OUO, restricted")

    # DDH Optional Metadata
    description: Optional[str] = Field(None, description="Service description for API/STAC metadata")
    tags: List[str] = Field(default_factory=list, description="Tags for categorization/search")

    # DDH Processing Options (Optional)
    processing_options: Dict[str, Any] = Field(
        default_factory=dict,
        description="""
        Processing options from DDH.

        Vector Options:
        - overwrite: bool (replace existing service)
        - lon_column: str (CSV longitude column)
        - lat_column: str (CSV latitude column)
        - wkt_column: str (WKT geometry column)
        - time_index: str | array (temporal indexing - Phase 2)
        - attribute_index: str | array (attribute indexing - Phase 2)

        Raster Options:
        - crs: int (EPSG code)
        - nodata_value: int (NoData value)
        - band_descriptions: dict (band metadata - Phase 2)
        - raster_collection: str (collection name - Phase 2)
        - temporal_order: dict (time-series mapping - Phase 2)

        Styling Options (Phase 2):
        - type: str (unique/classed/stretch)
        - property: str (attribute for visualization)
        - color_ramp: str | array (color palette)
        - classification: str (natural-breaks/quantile/equal/standard-deviation)
        - classes: int (number of classes)
        """
    )

    # Client Identifier
    client_id: str = Field(default="ddh", description="Client application identifier")

    # --- Computed Properties ---

    @property
    def source_location(self) -> str:
        """
        Construct Azure blob storage URL from container_name + file_name.

        Returns:
            Full Azure blob URL for the first file (if array) or single file
        """
        base_url = "https://rmhazuregeo.blob.core.windows.net"

        # Handle array of file names (raster collections)
        if isinstance(self.file_name, list):
            first_file = self.file_name[0]
            return f"{base_url}/{self.container_name}/{first_file}"

        # Handle single file name
        return f"{base_url}/{self.container_name}/{self.file_name}"

    @property
    def data_type(self) -> DataType:
        """
        Detect data type from file extension.

        Returns:
            DataType enum (RASTER, VECTOR, POINTCLOUD, MESH_3D, TABULAR)
        """
        # Get first file name if array
        file_name = self.file_name[0] if isinstance(self.file_name, list) else self.file_name

        # Extract extension
        ext = file_name.lower().split('.')[-1]

        # Map extension to data type
        if ext in ['geojson', 'gpkg', 'shp', 'zip', 'csv']:
            return DataType.VECTOR
        elif ext in ['tif', 'tiff', 'img', 'hdf', 'nc']:
            return DataType.RASTER
        elif ext in ['las', 'laz', 'e57']:
            return DataType.POINTCLOUD
        elif ext in ['obj', 'fbx', 'gltf', 'glb']:
            return DataType.MESH_3D
        elif ext in ['xlsx', 'parquet']:
            return DataType.TABULAR
        else:
            raise ValueError(f"Unsupported file format: {ext}")

    @property
    def stac_item_id(self) -> str:
        """
        Generate URL-safe STAC item_id from service_name.

        Example: "King County Parcels 2024" → "king-county-parcels-2024"
        """
        import re
        item_id = self.service_name.lower()
        item_id = item_id.replace(' ', '-')
        item_id = re.sub(r'[^a-z0-9\-_]', '', item_id)
        return item_id

    # --- Validators ---

    @field_validator('container_name')
    @classmethod
    def validate_container(cls, v: str) -> str:
        """Ensure container name follows naming convention"""
        valid_containers = [
            'bronze-vectors', 'bronze-rasters', 'bronze-misc', 'bronze-temp',
            'silver-cogs', 'silver-vectors', 'silver-mosaicjson', 'silver-stac-assets'
        ]
        if v not in valid_containers:
            raise ValueError(f"Container must be one of: {', '.join(valid_containers)}")
        return v

    @field_validator('access_level')
    @classmethod
    def validate_access_level(cls, v: str) -> str:
        """Ensure access level is valid"""
        valid_levels = ['public', 'OUO', 'restricted']
        if v not in valid_levels:
            raise ValueError(f"access_level must be one of: {', '.join(valid_levels)}")
        return v
```

### Change 3: Update `ApiRequest` Database Model

**Location**: Lines 120-217

**Add to metadata field description (line ~201):**

```python
metadata: Dict[str, Any] = Field(
    default_factory=dict,
    description="""
    Additional metadata about the request.

    DDH Metadata Fields:
    - service_name: str (human-readable service name, maps to STAC title)
    - stac_item_id: str (URL-safe STAC item identifier)
    - access_level: str (public/OUO/restricted - enforcement Phase 2)
    - description: str (service description for API/STAC)
    - tags: list (categorization/search tags)
    - client_id: str (client application identifier)
    - source_location: str (Azure blob URL)
    - submission_time: str (ISO 8601 timestamp)
    """
)
```

### Change 4: Update Exports (Bottom of File)

**Location**: Line ~326

**ADD:**
```python
# Export new enum
__all__ = [
    'PlatformRequestStatus',
    'DataType',
    'OperationType',  # NEW
    'PlatformRequest',
    'ApiRequest',
    'OrchestrationJob',
    'PLATFORM_TABLE_NAMES',
    'PLATFORM_PRIMARY_KEYS',
    'PLATFORM_INDEXES'
]
```

---

## 🔧 Changes to `triggers/trigger_platform.py`

### Change 1: Update Imports

**Location**: Lines 82-88

**ADD:**
```python
from core.models import (
    ApiRequest,
    PlatformRequestStatus,
    DataType,
    OperationType,  # NEW
    PlatformRequest
)
```

### Change 2: Update `platform_request_submit` HTTP Handler

**Location**: Lines 134-217

**BEFORE (line ~168-181):**
```python
# Create platform record
platform_record = ApiRequest(
    request_id=request_id,
    dataset_id=platform_req.dataset_id,
    resource_id=platform_req.resource_id,
    version_id=platform_req.version_id,
    data_type=platform_req.data_type.value,
    status=PlatformRequestStatus.PENDING,
    parameters=platform_req.parameters,
    metadata={
        'client_id': platform_req.client_id,
        'source_location': platform_req.source_location,
        'submission_time': datetime.utcnow().isoformat()
    }
)
```

**AFTER:**
```python
# Create platform record with DDH metadata
platform_record = ApiRequest(
    request_id=request_id,
    dataset_id=platform_req.dataset_id,
    resource_id=platform_req.resource_id,
    version_id=platform_req.version_id,
    data_type=platform_req.data_type.value,  # Computed from file extension
    status=PlatformRequestStatus.PENDING,
    parameters={
        'operation': platform_req.operation.value,
        'container_name': platform_req.container_name,
        'file_name': platform_req.file_name,
        'processing_options': platform_req.processing_options
    },
    metadata={
        'service_name': platform_req.service_name,
        'stac_item_id': platform_req.stac_item_id,  # Computed from service_name
        'access_level': platform_req.access_level,
        'description': platform_req.description,
        'tags': platform_req.tags,
        'client_id': platform_req.client_id,
        'source_location': platform_req.source_location,  # Computed from container + file
        'submission_time': datetime.utcnow().isoformat()
    }
)
```

### Change 3: Update `PlatformOrchestrator._determine_jobs()`

**Location**: Lines 326-401

**REPLACE ENTIRE METHOD:**

```python
def _determine_jobs(self, request: ApiRequest) -> List[Dict[str, Any]]:
    """
    Determine what CoreMachine jobs to create based on operation + data_type.

    This is where we implement the business logic of "what work needs
    to be done for this type of data with this operation".

    Args:
        request: ApiRequest with DDH parameters

    Returns:
        List of job configurations (job_type + parameters)
    """
    jobs = []
    operation = request.parameters.get('operation', 'CREATE')
    data_type = request.data_type
    source_location = request.metadata.get('source_location', '')
    file_name = request.parameters.get('file_name')
    processing_options = request.parameters.get('processing_options', {})

    logger.info(f"Determining jobs for operation={operation}, data_type={data_type}")

    # ========================================================================
    # CREATE OPERATION (Phase 1 - ACTIVE)
    # ========================================================================
    if operation == OperationType.CREATE.value:

        # ----------------------------------------------------------------
        # VECTOR CREATE: Ingest to PostGIS + STAC Catalog
        # ----------------------------------------------------------------
        if data_type == DataType.VECTOR.value:
            logger.info(f"  → Vector CREATE: ingest_vector + stac_catalog_vectors")

            # Determine table name from dataset_id + resource_id
            table_name = f"{request.dataset_id}_{request.resource_id}".lower()
            table_name = table_name.replace('-', '_')  # PostgreSQL-safe

            jobs.extend([
                {
                    'job_type': 'ingest_vector',
                    'parameters': {
                        'source_path': source_location,
                        'file_name': file_name,
                        'dataset_id': request.dataset_id,
                        'resource_id': request.resource_id,
                        'table_name': table_name,
                        'schema': 'geo',
                        # CSV-specific options (if present)
                        'lon_column': processing_options.get('lon_column'),
                        'lat_column': processing_options.get('lat_column'),
                        'wkt_column': processing_options.get('wkt_column'),
                        # Overwrite flag (default: false for CREATE)
                        'overwrite': processing_options.get('overwrite', False)
                    }
                }
                # NOTE: stac_catalog_vectors job is CHAINED automatically
                # by PlatformOrchestrator._handle_job_completion() callback
                # when ingest_vector completes successfully
            ])

        # ----------------------------------------------------------------
        # RASTER CREATE: Validate + Create COG
        # ----------------------------------------------------------------
        elif data_type == DataType.RASTER.value:
            # Check if this is a raster collection (array of file names)
            is_collection = isinstance(file_name, list) and len(file_name) > 1

            if is_collection:
                logger.info(f"  → Raster Collection CREATE: process_raster_collection (Phase 2)")
                # TODO: Implement raster collection workflow (Phase 2)
                # jobs.append({
                #     'job_type': 'process_raster_collection',
                #     'parameters': {
                #         'source_paths': [f"{source_location}/{f}" for f in file_name],
                #         'collection_name': processing_options.get('raster_collection'),
                #         'temporal_order': processing_options.get('temporal_order'),
                #         ...
                #     }
                # })
                logger.warning(f"Raster collections not yet implemented - skipping")

            else:
                logger.info(f"  → Raster CREATE: validate_raster_job + process_raster")

                jobs.extend([
                    {
                        'job_type': 'validate_raster_job',
                        'parameters': {
                            'source_path': source_location,
                            'file_name': file_name,
                            'dataset_id': request.dataset_id,
                            'resource_id': request.resource_id,
                            # Raster options (optional)
                            'target_crs': processing_options.get('crs'),
                            'nodata_value': processing_options.get('nodata_value')
                        }
                    },
                    {
                        'job_type': 'process_raster',
                        'parameters': {
                            'source_path': source_location,
                            'file_name': file_name,
                            'output_container': 'silver-cogs',
                            'dataset_id': request.dataset_id,
                            'resource_id': request.resource_id,
                            # Raster options (optional)
                            'target_crs': processing_options.get('crs'),
                            'nodata_value': processing_options.get('nodata_value'),
                            'band_descriptions': processing_options.get('band_descriptions')
                        }
                    }
                ])

        # ----------------------------------------------------------------
        # POINTCLOUD CREATE (Phase 2 - Placeholder)
        # ----------------------------------------------------------------
        elif data_type == DataType.POINTCLOUD.value:
            logger.warning(f"  → Point cloud CREATE not yet implemented (Phase 2)")
            # TODO: Implement point cloud workflow (Phase 2)
            # jobs.append({
            #     'job_type': 'process_pointcloud',
            #     'parameters': {
            #         'source_path': source_location,
            #         'file_name': file_name,
            #         'dataset_id': request.dataset_id
            #     }
            # })

        # ----------------------------------------------------------------
        # UNSUPPORTED DATA TYPE
        # ----------------------------------------------------------------
        else:
            logger.error(f"  → Unsupported data type: {data_type}")
            raise ValueError(f"CREATE operation not supported for data type: {data_type}")

    # ========================================================================
    # UPDATE OPERATION (Phase 2 - Placeholder)
    # ========================================================================
    elif operation == OperationType.UPDATE.value:
        logger.warning(f"UPDATE operation not yet implemented (Phase 2)")

        # TODO: Implement UPDATE logic (Phase 2)
        # UPDATE = Re-ingest with overwrite flag
        #
        # if data_type == DataType.VECTOR.value:
        #     jobs.append({
        #         'job_type': 'ingest_vector',
        #         'parameters': {
        #             'source_path': source_location,
        #             'overwrite': True,  # Key difference from CREATE
        #             'table_name': f"{request.dataset_id}_{request.resource_id}",
        #             'schema': 'geo'
        #         }
        #     })
        #     # Update STAC metadata (chained)
        #
        # elif data_type == DataType.RASTER.value:
        #     jobs.extend([
        #         {'job_type': 'validate_raster_job', ...},
        #         {'job_type': 'process_raster', 'parameters': {'overwrite': True, ...}}
        #     ])

        raise NotImplementedError("UPDATE operation coming in Phase 2")

    # ========================================================================
    # DELETE OPERATION (Phase 2 - Placeholder)
    # ========================================================================
    elif operation == OperationType.DELETE.value:
        logger.warning(f"DELETE operation not yet implemented (Phase 2)")

        # TODO: Implement DELETE logic (Phase 2)
        # DELETE = Remove from PostGIS/Storage + STAC catalog
        #
        # if data_type == DataType.VECTOR.value:
        #     jobs.append({
        #         'job_type': 'delete_vector_service',
        #         'parameters': {
        #             'table_name': f"{request.dataset_id}_{request.resource_id}",
        #             'schema': 'geo',
        #             'stac_item_id': request.metadata.get('stac_item_id')
        #         }
        #     })
        #
        # elif data_type == DataType.RASTER.value:
        #     jobs.append({
        #         'job_type': 'delete_raster_service',
        #         'parameters': {
        #             'dataset_id': request.dataset_id,
        #             'resource_id': request.resource_id,
        #             'stac_item_id': request.metadata.get('stac_item_id')
        #         }
        #     })

        raise NotImplementedError("DELETE operation coming in Phase 2")

    # ========================================================================
    # UNKNOWN OPERATION
    # ========================================================================
    else:
        logger.error(f"Unknown operation: {operation}")
        raise ValueError(f"Unknown operation: {operation}")

    logger.info(f"Determined {len(jobs)} jobs for request {request.request_id}")
    return jobs
```

### Change 4: Update `_handle_job_completion()` for STAC Chaining

**Location**: Lines 507-597

**FIND (line ~548-583):**
```python
# Job chaining logic - submit dependent jobs
if job_type == 'ingest_vector':
    # Vector ingestion complete → Submit STAC cataloging job
    logger.info(f"   🔗 Chaining: ingest_vector → stac_catalog_vectors")

    # Extract table name from job result
    table_name = result.get('table_name') or job_record.parameters.get('table_name')
    dataset_id = job_record.parameters.get('_platform_dataset') or job_record.parameters.get('dataset_id')

    if table_name:
        # Submit STAC catalog job
        import asyncio
        platform_request = self.platform_repo.get_request(platform_request_id)

        stac_job_id = asyncio.run(self._create_coremachine_job(
            platform_request,
            'stac_catalog_vectors',
            {
                'schema': 'geo',
                'table_name': table_name,
                'collection_id': dataset_id or 'vectors',
                'source_file': job_record.parameters.get('source_path')
            }
        ))
```

**REPLACE WITH:**
```python
# Job chaining logic - submit dependent jobs
if job_type == 'ingest_vector':
    # Vector ingestion complete → Submit STAC cataloging job
    logger.info(f"   🔗 Chaining: ingest_vector → stac_catalog_vectors")

    # Extract table name from job result
    table_name = result.get('table_name') or job_record.parameters.get('table_name')
    dataset_id = job_record.parameters.get('_platform_dataset') or job_record.parameters.get('dataset_id')

    # Get Platform request for metadata
    platform_request = self.platform_repo.get_request(platform_request_id)
    if not platform_request:
        logger.error(f"   ❌ Platform request {platform_request_id} not found - cannot chain STAC job")
        return

    # Get DDH metadata for STAC item
    stac_item_id = platform_request.metadata.get('stac_item_id')
    service_name = platform_request.metadata.get('service_name')
    description = platform_request.metadata.get('description')
    tags = platform_request.metadata.get('tags', [])
    access_level = platform_request.metadata.get('access_level')

    if table_name and stac_item_id:
        # Submit STAC catalog job with DDH metadata
        import asyncio

        stac_job_id = asyncio.run(self._create_coremachine_job(
            platform_request,
            'stac_catalog_vectors',
            {
                'schema': 'geo',
                'table_name': table_name,
                'collection_id': dataset_id or 'vectors',
                'source_file': job_record.parameters.get('source_path'),
                # DDH metadata for STAC
                'stac_item_id': stac_item_id,
                'title': service_name,
                'description': description,
                'keywords': tags,
                'access_level': access_level
            }
        ))
```

---

## 📝 Summary of Changes

### `core/models/platform.py`
1. ✅ Add `OperationType` enum (CREATE/UPDATE/DELETE)
2. ✅ Expand `PlatformRequest` DTO with DDH parameters
3. ✅ Add computed properties: `source_location`, `data_type`, `stac_item_id`
4. ✅ Add validators for `container_name` and `access_level`
5. ✅ Update `ApiRequest.metadata` field description

### `triggers/trigger_platform.py`
1. ✅ Update imports to include `OperationType`
2. ✅ Update `platform_request_submit()` to capture DDH metadata
3. ✅ Rewrite `_determine_jobs()` with CREATE logic + UPDATE/DELETE placeholders
4. ✅ Update `_handle_job_completion()` to pass DDH metadata to STAC jobs

---

## 🎯 Testing Checklist

After implementing these changes:

### Test 1: Vector CREATE
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/platform/submit \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "test-parcels",
    "resource_id": "sample-data",
    "version_id": "v1.0",
    "operation": "CREATE",
    "container_name": "bronze-vectors",
    "file_name": "test.geojson",
    "service_name": "Test Parcels Service",
    "access_level": "public",
    "description": "Test vector service",
    "tags": ["test"],
    "processing_options": {}
  }'
```

**Expected**:
- ✅ `data_type` computed as "vector"
- ✅ `source_location` computed as "https://rmhazuregeo.blob.core.windows.net/bronze-vectors/test.geojson"
- ✅ `stac_item_id` computed as "test-parcels-service"
- ✅ Jobs created: `ingest_vector` (then `stac_catalog_vectors` via callback)

### Test 2: Raster CREATE
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/platform/submit \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "test-landsat",
    "resource_id": "scene-001",
    "version_id": "v1.0",
    "operation": "CREATE",
    "container_name": "bronze-rasters",
    "file_name": "landsat.tif",
    "service_name": "Test Landsat Scene",
    "access_level": "public",
    "processing_options": {
      "crs": 4326,
      "nodata_value": 0
    }
  }'
```

**Expected**:
- ✅ `data_type` computed as "raster"
- ✅ Jobs created: `validate_raster_job`, `process_raster`

### Test 3: UPDATE/DELETE Operations (Should Fail)
```bash
# UPDATE - should return 501 Not Implemented
curl -X POST .../api/platform/submit -d '{"operation": "UPDATE", ...}'

# DELETE - should return 501 Not Implemented
curl -X POST .../api/platform/submit -d '{"operation": "DELETE", ...}'
```

**Expected**:
- ❌ NotImplementedError with message "UPDATE/DELETE operation coming in Phase 2"

---

## 📚 Next Steps

1. **Implement changes** to `core/models/platform.py`
2. **Implement changes** to `triggers/trigger_platform.py`
3. **Test locally** with sample requests
4. **Deploy** to Azure Functions
5. **Verify** with Application Insights logs
6. **Document** APIM policy (next phase)

---

**Document Status**: ✅ READY FOR IMPLEMENTATION
**Last Updated**: 1 NOV 2025
