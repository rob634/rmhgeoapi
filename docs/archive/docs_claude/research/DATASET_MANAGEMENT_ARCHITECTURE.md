# Dataset Management Layer Architecture

**Date**: 25 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: High-level application layer for managing Dataset lifecycle and REST API endpoints

## Executive Summary

The Dataset Management Layer provides a **client-facing API** that sits above CoreMachine to handle external application requests. It abstracts away the complexity of jobs/stages/tasks, providing a simple request/response pattern:

1. **Client requests dataset** → Gets 202 Accepted + tracking ID
2. **Client polls status** → Gets progress updates
3. **Dataset ready** → Client receives API endpoint for data access

This is the **external-facing** layer, while CoreMachine remains the **internal** orchestration engine.

## Key Distinction from CoreMachine

| Aspect | CoreMachine (Internal) | Dataset Layer (External) |
|--------|------------------------|-------------------------|
| **Audience** | Internal system | External applications |
| **Abstraction** | Jobs→Stages→Tasks | Simple dataset requests |
| **Complexity** | Full visibility | Hidden complexity |
| **Response** | Job IDs, task details | Dataset ID + status |
| **Tracking** | `/api/jobs/{job_id}` | `/api/datasets/{dataset_key}/status` |
| **Result** | Task results | REST API endpoint |

## Architecture Overview

```
External Applications (Frontend, APIs, etc.)
         │
         ▼
    HTTP Request
         │
         ▼
┌─────────────────────────────────────────────┐
│     Dataset Management Layer (New)          │
│                                              │
│  ┌─────────────┐  ┌──────────────────────┐  │
│  │   Dataset   │  │  Dataset Orchestrator │  │
│  │   Registry  │  │                       │  │
│  └─────────────┘  └──────────────────────┘  │
│                                              │
│  ┌─────────────┐  ┌──────────────────────┐  │
│  │   Dataset   │  │   Dataset Lifecycle   │  │
│  │   Metadata  │  │      Manager          │  │
│  └─────────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│          CoreMachine (Existing)             │
│                                              │
│  Orchestrates individual jobs via           │
│  Job→Stage→Task pattern                     │
└─────────────────────────────────────────────┘
                    │
                    ▼
         Service Bus / PostgreSQL / Blob
```

## Core Components

### 1. Dataset Model

```python
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from enum import Enum
from datetime import datetime

class DatasetStatus(str, Enum):
    REQUESTED = "requested"
    PROVISIONING = "provisioning"
    PROCESSING = "processing"
    READY = "ready"
    UPDATING = "updating"
    FAILED = "failed"
    DEPRECATED = "deprecated"
    DELETED = "deleted"

class DatasetRequest(BaseModel):
    """External application request for dataset creation/update"""
    dataset_id: str          # e.g., "parcels_2025"
    resource_id: str         # e.g., "county_assessor"
    version_id: str          # e.g., "v2025.10.1"

    # What type of dataset to create
    dataset_type: str        # "vector", "raster", "collection", "mosaic"

    # Source data references
    source_data: Dict[str, Any]  # Blob paths, database tables, etc.

    # Processing requirements
    processing_config: Dict[str, Any]  # COG creation, tiling, etc.

    # API configuration
    api_config: Dict[str, Any]  # TiTiler settings, OGC API config

    # Metadata
    metadata: Dict[str, Any]  # Description, attribution, license

    # Callback configuration
    callback_url: Optional[str] = None
    callback_headers: Optional[Dict[str, str]] = None

class DatasetRecord(BaseModel):
    """Persistent dataset record in database"""
    # Identity
    dataset_id: str
    resource_id: str
    version_id: str

    # Unique composite key
    dataset_key: str  # SHA256(dataset_id + resource_id + version_id)

    # Status tracking
    status: DatasetStatus
    status_history: List[Dict[str, Any]]

    # Job orchestration
    job_chain: List[str]  # Ordered list of job_ids to execute
    current_job_index: int = 0
    completed_jobs: List[str] = []
    failed_jobs: List[str] = []

    # REST API endpoint
    api_endpoint: Optional[str] = None  # e.g., "/datasets/parcels_2025/county_assessor/v2025.10.1"
    api_type: Optional[str] = None      # "ogc-features", "titiler", "stac"

    # Data locations
    data_locations: Dict[str, Any]  # Where processed data lives

    # Timestamps
    requested_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    updated_at: datetime

    # Request details
    original_request: DatasetRequest
    processing_metadata: Dict[str, Any] = {}
```

### 2. Dataset Orchestrator

```python
class DatasetOrchestrator:
    """
    High-level orchestrator that manages dataset lifecycle.
    Sits above CoreMachine and coordinates multiple jobs.
    """

    def __init__(self, core_machine: CoreMachine, config: AppConfig):
        self.core_machine = core_machine
        self.config = config
        self.dataset_repo = DatasetRepository()
        self.job_planner = DatasetJobPlanner()
        self.api_provisioner = ApiProvisioner()

    def create_dataset(self, request: DatasetRequest) -> DatasetRecord:
        """
        Main entry point for dataset creation.

        1. Validate request
        2. Create dataset record
        3. Plan job chain based on dataset type
        4. Submit first job to CoreMachine
        5. Return dataset record with tracking info
        """
        # Generate unique key
        dataset_key = self._generate_dataset_key(request)

        # Check for existing dataset (idempotency)
        existing = self.dataset_repo.get_by_key(dataset_key)
        if existing:
            return existing

        # Plan job chain based on dataset type
        job_chain = self.job_planner.plan_jobs(request)

        # Create dataset record
        dataset_record = DatasetRecord(
            dataset_id=request.dataset_id,
            resource_id=request.resource_id,
            version_id=request.version_id,
            dataset_key=dataset_key,
            status=DatasetStatus.PROVISIONING,
            job_chain=job_chain,
            original_request=request,
            requested_at=datetime.utcnow()
        )

        # Persist to database
        self.dataset_repo.create(dataset_record)

        # Submit first job
        self._submit_next_job(dataset_record)

        return dataset_record

    def handle_job_completion(self, job_id: str, job_result: Dict[str, Any]):
        """
        Called when a job completes (via webhook or queue message).
        Advances dataset processing to next job or completes dataset.
        """
        # Find dataset by job_id
        dataset = self.dataset_repo.get_by_job_id(job_id)
        if not dataset:
            logger.warning(f"No dataset found for job {job_id}")
            return

        # Update dataset with job results
        dataset.completed_jobs.append(job_id)
        dataset.processing_metadata[job_id] = job_result

        # Check if more jobs to run
        if dataset.current_job_index < len(dataset.job_chain) - 1:
            # Submit next job
            dataset.current_job_index += 1
            self._submit_next_job(dataset)
        else:
            # All jobs complete - provision API endpoint
            self._complete_dataset(dataset)

    def _submit_next_job(self, dataset: DatasetRecord):
        """Submit next job in chain to CoreMachine"""
        job_type = dataset.job_chain[dataset.current_job_index]

        # Build job parameters from dataset context
        job_params = self._build_job_params(dataset, job_type)

        # Add dataset tracking metadata
        job_params["_dataset_key"] = dataset.dataset_key
        job_params["_dataset_job_index"] = dataset.current_job_index

        # Submit to CoreMachine (reuses existing job types)
        job_id = self._submit_job(job_type, job_params)

        # Update dataset status
        dataset.status = DatasetStatus.PROCESSING
        self.dataset_repo.update(dataset)

    def _complete_dataset(self, dataset: DatasetRecord):
        """Provision API endpoint and mark dataset as ready"""
        # Provision REST API endpoint based on type
        api_config = self.api_provisioner.provision(
            dataset_type=dataset.original_request.dataset_type,
            data_locations=dataset.data_locations,
            api_config=dataset.original_request.api_config
        )

        # Update dataset
        dataset.api_endpoint = api_config["endpoint"]
        dataset.api_type = api_config["type"]
        dataset.status = DatasetStatus.READY
        dataset.completed_at = datetime.utcnow()

        self.dataset_repo.update(dataset)

        # Send callback if configured
        if dataset.original_request.callback_url:
            self._send_callback(dataset)
```

### 3. Dataset Job Planner

```python
class DatasetJobPlanner:
    """
    Plans job chains based on dataset type and requirements.
    Maps high-level dataset requests to concrete job sequences.
    """

    # Job chain templates for different dataset types
    JOB_CHAINS = {
        "vector": [
            "ingest_vector",        # Load into PostGIS
            "stac_catalog_vectors"  # Create STAC metadata
        ],
        "raster": [
            "validate_raster",      # Validate and extract metadata
            "process_raster",       # Create COG
            "stac_catalog_raster"   # Create STAC item
        ],
        "raster_collection": [
            "validate_raster",           # Validate each raster
            "process_raster_collection", # Process collection
            "create_mosaic_json",        # Create MosaicJSON
            "stac_catalog_collection"    # Create STAC collection
        ],
        "large_raster": [
            "process_large_raster",  # Tile and process
            "stac_catalog_tiles"     # Catalog tiles as collection
        ]
    }

    def plan_jobs(self, request: DatasetRequest) -> List[str]:
        """
        Determines job execution chain based on dataset type.
        Can be dynamic based on data characteristics.
        """
        base_chain = self.JOB_CHAINS.get(request.dataset_type, [])

        # Add conditional jobs based on requirements
        if request.processing_config.get("generate_statistics"):
            base_chain.append("generate_statistics")

        if request.processing_config.get("build_overviews"):
            base_chain.append("build_overviews")

        if request.api_config.get("enable_tiles"):
            base_chain.append("generate_tile_cache")

        return base_chain
```

### 4. API Provisioner

```python
class ApiProvisioner:
    """
    Provisions REST API endpoints for completed datasets.
    Configures TiTiler, OGC API, or custom endpoints.
    """

    def provision(self, dataset_type: str, data_locations: Dict,
                  api_config: Dict) -> Dict[str, Any]:
        """
        Creates REST API endpoint configuration.

        Returns endpoint URL and configuration details.
        """
        if dataset_type == "vector":
            return self._provision_ogc_features(data_locations, api_config)
        elif dataset_type in ["raster", "raster_collection"]:
            return self._provision_titiler(data_locations, api_config)
        elif dataset_type == "large_raster":
            return self._provision_tile_server(data_locations, api_config)
        else:
            raise ValueError(f"Unknown dataset type: {dataset_type}")

    def _provision_titiler(self, data_locations: Dict, config: Dict) -> Dict:
        """Configure TiTiler endpoint for COG access"""
        # Register COG with TiTiler
        # Configure rendering parameters
        # Set up caching if enabled
        return {
            "endpoint": f"/cog/tiles/{{z}}/{{x}}/{{y}}",
            "type": "titiler",
            "config": {
                "source": data_locations["cog_path"],
                "cache_enabled": config.get("cache", False)
            }
        }
```

## Integration Points

### 1. HTTP API Endpoints

```python
# New endpoints in function_app.py

@app.route(route="datasets", methods=["POST"])
def create_dataset(req: func.HttpRequest) -> func.HttpResponse:
    """Create new dataset from external application request"""
    request = DatasetRequest.model_validate_json(req.get_body())
    dataset = dataset_orchestrator.create_dataset(request)
    return func.HttpResponse(dataset.model_dump_json(), status_code=202)

@app.route(route="datasets/{dataset_key}", methods=["GET"])
def get_dataset_status(req: func.HttpRequest) -> func.HttpResponse:
    """Get dataset status and metadata"""
    dataset_key = req.route_params.get('dataset_key')
    dataset = dataset_repo.get_by_key(dataset_key)
    return func.HttpResponse(dataset.model_dump_json())

@app.route(route="datasets/{dataset_key}", methods=["DELETE"])
def delete_dataset(req: func.HttpRequest) -> func.HttpResponse:
    """Mark dataset for deletion"""
    dataset_key = req.route_params.get('dataset_key')
    dataset_orchestrator.delete_dataset(dataset_key)
    return func.HttpResponse(status_code=204)
```

### 2. Database Schema

```sql
-- New table for dataset management
CREATE TABLE app.datasets (
    dataset_key VARCHAR(64) PRIMARY KEY,  -- SHA256 hash
    dataset_id VARCHAR(255) NOT NULL,
    resource_id VARCHAR(255) NOT NULL,
    version_id VARCHAR(50) NOT NULL,

    status VARCHAR(20) NOT NULL,
    status_history JSONB DEFAULT '[]',

    job_chain JSONB NOT NULL,  -- Array of job types
    current_job_index INT DEFAULT 0,
    completed_jobs JSONB DEFAULT '[]',
    failed_jobs JSONB DEFAULT '[]',

    api_endpoint VARCHAR(500),
    api_type VARCHAR(50),
    api_config JSONB,

    data_locations JSONB,
    original_request JSONB NOT NULL,
    processing_metadata JSONB DEFAULT '{}',

    requested_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Composite unique constraint
    CONSTRAINT unique_dataset_identity
        UNIQUE(dataset_id, resource_id, version_id),

    -- Indexes for queries
    INDEX idx_dataset_status (status),
    INDEX idx_dataset_requested (requested_at)
);

-- Link jobs to datasets
ALTER TABLE app.jobs
ADD COLUMN dataset_key VARCHAR(64),
ADD CONSTRAINT fk_dataset
    FOREIGN KEY (dataset_key)
    REFERENCES app.datasets(dataset_key);
```

### 3. Service Bus Integration

```python
@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="dataset-completion-events"
)
def process_dataset_completion(msg: func.ServiceBusMessage):
    """
    Handle job completion events and advance dataset processing.

    This is triggered when a job completes and needs to advance
    the parent dataset to the next step.
    """
    event = json.loads(msg.get_body())
    dataset_orchestrator.handle_job_completion(
        job_id=event["job_id"],
        job_result=event["result"]
    )
```

## Implementation Strategy

### Phase 1: Core Infrastructure (Week 1)
1. Create dataset models and database schema
2. Implement DatasetRepository for persistence
3. Add dataset_key field to existing job records
4. Create basic HTTP endpoints

### Phase 2: Orchestration (Week 2)
1. Implement DatasetOrchestrator
2. Create DatasetJobPlanner with basic templates
3. Add job completion webhook/queue handler
4. Test with simple vector dataset

### Phase 3: API Provisioning (Week 3)
1. Implement ApiProvisioner for each dataset type
2. Configure TiTiler integration
3. Set up OGC API Features
4. Add caching configuration

### Phase 4: Advanced Features (Week 4)
1. Add dataset versioning and updates
2. Implement deletion and cleanup
3. Add monitoring and metrics
4. Create administrative UI

## Client Interaction Pattern

### Simple Request/Response Flow

```python
# 1. CLIENT MAKES REQUEST
POST /api/datasets
{
    "dataset_id": "parcels_2025",
    "resource_id": "county_assessor",
    "version_id": "v2025.10.1",
    "dataset_type": "vector",
    "source_data": {
        "blob_path": "azure://bronze/parcels/2025/parcels.gpkg"
    }
}

# 2. IMMEDIATE RESPONSE (202 Accepted)
{
    "dataset_key": "d7f8a9b3c2...",  # Unique tracking ID
    "status": "provisioning",
    "status_url": "/api/datasets/d7f8a9b3c2.../status",
    "estimated_completion": "2025-10-25T15:30:00Z"
}

# 3. CLIENT POLLS STATUS
GET /api/datasets/d7f8a9b3c2.../status

# Progress Response (while processing)
{
    "dataset_key": "d7f8a9b3c2...",
    "status": "processing",
    "progress": {
        "current_step": "ingesting_vector",
        "steps_completed": 1,
        "total_steps": 3,
        "percent_complete": 33
    },
    "message": "Loading GeoPackage into PostGIS..."
}

# 4. FINAL RESPONSE (when ready)
{
    "dataset_key": "d7f8a9b3c2...",
    "status": "ready",
    "api_endpoint": "https://rmhgeoapibeta.../api/data/parcels_2025/county_assessor/v2025.10.1",
    "api_docs": "https://rmhgeoapibeta.../api/data/parcels_2025/docs",
    "capabilities": {
        "ogc_features": true,
        "tiles": true,
        "bulk_export": true
    },
    "metadata": {
        "feature_count": 125430,
        "bbox": [-117.5, 32.5, -116.0, 33.5],
        "crs": "EPSG:4326"
    }
}
```

### What Happens Behind the Scenes

```
Client Request → Dataset Layer → CoreMachine → Multiple Jobs
                     ↓                              ↓
              Simple Status                Complex Orchestration
                     ↓                              ↓
              "33% complete"            Job1→Tasks, Job2→Tasks...
```

The client never sees:
- Individual job IDs
- Task execution details
- Stage transitions
- Retry logic
- Service Bus messages

The client only sees:
- Dataset tracking ID
- Simple status (provisioning, processing, ready, failed)
- Progress percentage
- Final API endpoint when ready

## Example Workflows

### Example 1: Vector Dataset Creation (Full Flow)

```bash
# 1. External app requests dataset
curl -X POST https://rmhgeoapibeta.../api/datasets \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "parcels_2025",
    "resource_id": "county_assessor",
    "version_id": "v2025.10.1",
    "dataset_type": "vector",
    "source_data": {
        "blob_path": "azure://bronze/parcels/2025/parcels.gpkg"
    }
  }'

# Response: 202 Accepted
# {
#   "dataset_key": "d7f8a9b3c2...",
#   "status_url": "/api/datasets/d7f8a9b3c2.../status"
# }

# 2. External app polls for status (every 10 seconds)
curl https://rmhgeoapibeta.../api/datasets/d7f8a9b3c2.../status

# 3. When ready, access the data
curl https://rmhgeoapibeta.../api/data/parcels_2025/county_assessor/v2025.10.1/items?limit=100
```

### What CoreMachine Does (Hidden from Client)

```python
# Behind the scenes, Dataset Layer creates these jobs:
# 1. ingest_vector -> Loads GPKG into PostGIS
#    - Creates job_id: abc123...
#    - Runs 5 stages with 20 tasks
# 2. stac_catalog_vectors -> Creates STAC metadata
#    - Creates job_id: def456...
#    - Runs 2 stages with 10 tasks
#
# Client never sees these details!
```

### Example 2: Large Raster Collection

```python
# External application request
request = {
    "dataset_id": "imagery_2025",
    "resource_id": "aerial_survey",
    "version_id": "v2025.Q3",
    "dataset_type": "raster_collection",
    "source_data": {
        "blob_pattern": "azure://bronze/imagery/2025/Q3/*.tif"
    },
    "processing_config": {
        "create_cogs": true,
        "target_resolution": 0.3,
        "compression": "DEFLATE"
    },
    "api_config": {
        "enable_mosaic": true,
        "default_colormap": "viridis"
    }
}

# Results in job chain:
# 1. validate_raster (multiple parallel tasks)
# 2. process_raster_collection
# 3. create_mosaic_json
# 4. stac_catalog_collection
# 5. API endpoint: /datasets/imagery_2025/aerial_survey/v2025.Q3
```

## Benefits

1. **Abstraction**: External apps don't need to understand jobs/stages/tasks
2. **Idempotency**: Same dataset request always produces same result
3. **Tracking**: Complete visibility into dataset processing status
4. **Flexibility**: Job chains can be dynamic based on data characteristics
5. **Reusability**: Leverages existing CoreMachine jobs
6. **Scalability**: Each dataset processes independently
7. **Versioning**: Built-in support for multiple versions

## Integration with Existing Architecture

The Dataset Management Layer is **additive** - it doesn't change CoreMachine or existing jobs:

- **CoreMachine**: Continues to orchestrate individual jobs
- **Jobs**: Remain focused on specific tasks (ingest, process, catalog)
- **Service Bus**: Handles both job messages and dataset events
- **Database**: Adds dataset table linked to jobs table

This design maintains separation of concerns while adding the high-level orchestration needed for external application integration.