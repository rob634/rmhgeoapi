# Platform-as-a-Service Architecture for Data Processing

**Date**: 25 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Platform service that processes data into REST APIs for multiple client applications

## Context and Vision

This is a **"Platform in a Box"** - a data processing service that:
1. Accepts requests from various client applications
2. Processes raw data into accessible REST APIs
3. Returns endpoint URLs and metadata to the requesting application
4. Remains agnostic to the client's internal data model

**Primary Client**: Data Catalog Application
- Manages metadata, user submissions, discovery
- Has its own hierarchy: Dataset → Resources → Versions
- We DON'T manage their metadata - we just process data

**Future Clients**: Any application needing data processing
- Analytics platforms
- Visualization tools
- Mobile applications
- Third-party integrations

## Architectural Philosophy

```
┌──────────────────────────────────────────────────────┐
│                  CLIENT APPLICATIONS                  │
│                                                        │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────┐  │
│  │Data Catalog │  │Analytics App │  │  Mobile App │  │
│  │             │  │              │  │             │  │
│  │ Dataset     │  │   Custom     │  │   Custom    │  │
│  │  └Resource  │  │   Models     │  │   Models    │  │
│  │    └Version │  │              │  │             │  │
│  └─────────────┘  └──────────────┘  └─────────────┘  │
└────────────────────┬─────────────┬──────────┬────────┘
                     │             │           │
                     ▼             ▼           ▼
              ┌────────────────────────────────────┐
              │     PLATFORM SERVICE (Our Box)     │
              │                                    │
              │  "Give me data, I'll give you API" │
              │                                    │
              │  • Accepts processing requests     │
              │  • Returns endpoint URLs           │
              │  • Agnostic to client models       │
              └────────────────────────────────────┘
```

## Key Design Principles

### 1. Platform Agnosticism
The platform doesn't enforce the Dataset→Resource→Version hierarchy. It accepts it as **optional context** but works with any identifier scheme.

### 2. Client Owns Metadata
- **Client manages**: Descriptions, tags, users, permissions, discovery
- **Platform manages**: Data processing, API provisioning, endpoint availability

### 3. Flexible Identification
Clients can use their own ID schemes. We just need enough info to create unique endpoints.

## API Design for Multiple Clients

### Universal Processing Request

```python
class ProcessingRequest(BaseModel):
    """
    Universal request that any client can use.
    Flexible enough for different organizational models.
    """

    # Client identification
    client_id: str                    # Which application is requesting
    client_request_id: str            # Client's tracking ID

    # Data identification (flexible)
    identifiers: Dict[str, str]       # Client-specific IDs
    # For catalog: {"dataset_id": "X", "resource_id": "Y", "version_id": "Z"}
    # For analytics: {"project_id": "A", "analysis_id": "B"}
    # For mobile: {"app_id": "M", "layer_id": "N"}

    # Processing instructions
    data_type: str                    # "vector", "raster", "collection"
    source_location: str              # Where to find the data
    processing_options: Dict[str, Any]  # COG, tiling, etc.

    # API preferences
    api_type: str = "auto"           # "ogc", "tiles", "stac", "auto"
    api_options: Dict[str, Any] = {} # Client-specific API config

    # Callback
    callback_url: Optional[str]      # Where to send completion notice
    callback_auth: Optional[Dict]    # Auth headers for callback

class ProcessingResponse(BaseModel):
    """
    Universal response that provides what clients need.
    """

    # Tracking
    platform_request_id: str          # Our internal tracking ID
    client_request_id: str            # Echo back their ID
    status: str                       # "accepted", "processing", "ready", "failed"

    # Progress
    status_url: str                   # Where to check progress
    estimated_completion: Optional[datetime]

    # Results (when ready)
    api_endpoints: Dict[str, str] = {}  # Multiple possible endpoints
    # {
    #   "features": "https://.../ogc/features",
    #   "tiles": "https://.../tiles/{z}/{x}/{y}",
    #   "download": "https://.../download/data.gpkg"
    # }

    # Metadata about processed data
    data_characteristics: Dict[str, Any] = {}
    # {
    #   "feature_count": 10000,
    #   "bbox": [...],
    #   "file_size": "25MB",
    #   "processing_time": "45s"
    # }
```

## Integration Pattern for Data Catalog

### Catalog's Perspective

```python
# Data Catalog has its own model
class CatalogDataset:
    dataset_id: str
    title: str
    description: str
    owner: User
    resources: List[CatalogResource]

class CatalogResource:
    resource_id: str
    resource_type: str
    versions: List[CatalogVersion]

class CatalogVersion:
    version_id: str
    upload_date: datetime
    file_path: str
    processed: bool
    api_endpoint: Optional[str]  # This comes from us!
```

### How Catalog Uses Our Platform

```python
# When user uploads data to catalog
def handle_data_upload(dataset_id: str, resource_id: str, version_id: str, file_path: str):

    # Catalog stores its metadata
    catalog_version = CatalogVersion(
        version_id=version_id,
        upload_date=datetime.now(),
        file_path=file_path,
        processed=False
    )
    catalog_db.save(catalog_version)

    # Request processing from platform
    platform_request = ProcessingRequest(
        client_id="data_catalog_v1",
        client_request_id=f"catalog_{dataset_id}_{resource_id}_{version_id}",
        identifiers={
            "dataset_id": dataset_id,
            "resource_id": resource_id,
            "version_id": version_id
        },
        data_type="vector",  # Determined by catalog
        source_location=file_path,
        processing_options={
            "target_crs": "EPSG:4326"
        },
        callback_url="https://catalog.app/webhook/processing-complete"
    )

    # Send to platform
    response = platform_api.process_data(platform_request)

    # Store platform tracking ID
    catalog_version.platform_request_id = response.platform_request_id
    catalog_db.update(catalog_version)

# When platform sends completion callback
def handle_platform_callback(callback_data):
    # Find the catalog record
    catalog_version = catalog_db.find_by_platform_id(callback_data.platform_request_id)

    # Update with API endpoints
    catalog_version.api_endpoint = callback_data.api_endpoints["features"]
    catalog_version.processed = True
    catalog_db.update(catalog_version)

    # Catalog can now show the data is available!
```

## Platform Internal Architecture

### Request Router

```python
class PlatformRequestRouter:
    """
    Routes requests from different clients to appropriate processors.
    Maintains client-agnostic processing.
    """

    def process_request(self, request: ProcessingRequest) -> ProcessingResponse:
        # Generate platform-internal ID (not tied to client's model)
        platform_id = self._generate_platform_id(request)

        # Check for duplicate requests (idempotency)
        existing = self.request_store.find_duplicate(request)
        if existing:
            return self._get_existing_response(existing)

        # Determine processing pipeline based on data_type
        pipeline = self._select_pipeline(request.data_type)

        # Create processing job(s)
        jobs = pipeline.plan_jobs(
            source=request.source_location,
            options=request.processing_options
        )

        # Submit to CoreMachine (existing infrastructure)
        for job in jobs:
            job["_platform_request_id"] = platform_id
            job["_client_id"] = request.client_id
            job["_callback_url"] = request.callback_url
            self.core_machine.submit_job(job)

        # Return immediate response
        return ProcessingResponse(
            platform_request_id=platform_id,
            client_request_id=request.client_request_id,
            status="accepted",
            status_url=f"/platform/status/{platform_id}",
            estimated_completion=self._estimate_completion(request)
        )

    def _generate_platform_id(self, request: ProcessingRequest) -> str:
        """
        Generate ID that's unique but allows deduplication.
        Based on actual data processing, not client's organization.
        """
        unique_elements = [
            request.source_location,
            request.data_type,
            json.dumps(request.processing_options, sort_keys=True)
        ]
        return hashlib.sha256("".join(unique_elements).encode()).hexdigest()[:16]
```

### Endpoint Builder

```python
class EndpointBuilder:
    """
    Builds API endpoints based on client preferences and data characteristics.
    Can create multiple endpoint types for the same data.
    """

    def build_endpoints(self, request: ProcessingRequest, processed_data_location: str) -> Dict[str, str]:
        endpoints = {}

        # Build URL path based on client's identifiers
        if request.client_id == "data_catalog_v1":
            # Use their Dataset/Resource/Version structure
            base_path = f"/data/{request.identifiers['dataset_id']}/{request.identifiers['resource_id']}/{request.identifiers['version_id']}"
        else:
            # Generic path for other clients
            base_path = f"/api/{request.client_id}/{request.client_request_id}"

        # Add appropriate endpoints based on data type
        if request.data_type == "vector":
            endpoints["features"] = f"{base_path}/ogc/features"
            endpoints["tiles"] = f"{base_path}/tiles/{{z}}/{{x}}/{{y}}"
            endpoints["download"] = f"{base_path}/download"

        elif request.data_type == "raster":
            endpoints["cog"] = f"{base_path}/cog"
            endpoints["tiles"] = f"{base_path}/cog/tiles/{{z}}/{{x}}/{{y}}"
            endpoints["statistics"] = f"{base_path}/statistics"

        return endpoints
```

## Database Schema (Platform-Agnostic)

```sql
-- Platform processing requests (not tied to any client's model)
CREATE TABLE platform.processing_requests (
    platform_request_id VARCHAR(16) PRIMARY KEY,
    client_id VARCHAR(50) NOT NULL,
    client_request_id VARCHAR(255) NOT NULL,

    -- Flexible identifier storage
    client_identifiers JSONB NOT NULL,  -- Whatever IDs the client uses

    -- Processing details
    data_type VARCHAR(50) NOT NULL,
    source_location TEXT NOT NULL,
    processing_options JSONB,

    -- Status
    status VARCHAR(20) NOT NULL,
    progress_percent INT DEFAULT 0,

    -- Results
    api_endpoints JSONB,  -- Multiple endpoints
    data_characteristics JSONB,  -- Info about processed data

    -- Tracking
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,

    -- Jobs (internal orchestration)
    job_ids JSONB DEFAULT '[]',  -- CoreMachine job IDs

    -- Unique constraint for deduplication
    CONSTRAINT unique_processing UNIQUE(source_location, data_type, processing_options),

    -- Indexes
    INDEX idx_client (client_id, client_request_id),
    INDEX idx_status (status),
    INDEX idx_created (created_at)
);
```

## Benefits of This Architecture

### For the Data Catalog
1. **Simple Integration**: Just send data, get back endpoints
2. **Maintains Control**: Keeps its own metadata and user management
3. **Flexible Versioning**: Can organize data however it wants
4. **No Lock-in**: Could switch to another processing service

### For Future Applications
1. **No Forced Structure**: Don't need to adopt Dataset/Resource/Version
2. **Custom Workflows**: Can request specific processing pipelines
3. **Multiple Endpoints**: Get various API types for same data
4. **White-label Ready**: Endpoints can match their URL structure

### For the Platform
1. **Client Agnostic**: Not tied to catalog's data model
2. **Reusable Core**: CoreMachine handles all processing
3. **Scalable**: Each client isolated from others
4. **Maintainable**: Clear separation of concerns

## Example: Different Clients, Same Platform

```python
# Data Catalog Request
{
    "client_id": "data_catalog_v1",
    "identifiers": {
        "dataset_id": "census_2020",
        "resource_id": "blocks",
        "version_id": "v1.2"
    },
    "data_type": "vector",
    "source_location": "azure://uploads/census/blocks_v1.2.gpkg"
}
# Result: /data/census_2020/blocks/v1.2/ogc/features

# Analytics Platform Request
{
    "client_id": "analytics_platform",
    "identifiers": {
        "project_id": "market_analysis",
        "layer_id": "demographics"
    },
    "data_type": "vector",
    "source_location": "azure://projects/market/demographics.shp"
}
# Result: /api/analytics_platform/market_analysis/demographics/ogc/features

# Mobile App Request
{
    "client_id": "field_collector_app",
    "identifiers": {
        "org_id": "water_district",
        "survey_id": "2025_inspection"
    },
    "data_type": "vector",
    "source_location": "azure://mobile/inspections_2025.geojson"
}
# Result: /api/field_collector_app/water_district/2025_inspection/tiles/{z}/{x}/{y}
```

All three clients use the same platform, but maintain their own organizational models!