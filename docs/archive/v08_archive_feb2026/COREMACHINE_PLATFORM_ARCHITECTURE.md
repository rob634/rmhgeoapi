# CoreMachine + Platform Architecture

**Date**: 26 OCT 2025
**Purpose**: Two-layer architecture combining Platform-as-a-Service with CoreMachine orchestration

---

## 🏗️ Two-Layer Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                    CLIENT APPLICATIONS                            │
│  • Data Catalog (Dataset → Resource → Version hierarchy)         │
│  • Analytics Apps (Custom project models)                         │
│  • Mobile Apps (App-specific data organization)                   │
│  • Third-party integrations (Flexible schemas)                    │
└─────────────────────────┬────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│                   LAYER 1: PLATFORM SERVICE                       │
│                   (Client-Agnostic REST API)                      │
│                                                                   │
│  Purpose: "Give me data, I'll give you API endpoints"            │
│                                                                   │
│  Input:  ProcessingRequest                                       │
│    • client_id: str (which app is requesting)                    │
│    • identifiers: Dict[str,str] (client's own IDs)               │
│    • data_type: str ("vector", "raster", "collection")           │
│    • source_location: str (where to find data)                   │
│    • processing_options: Dict (COG, tiling, etc.)                │
│                                                                   │
│  Output: ProcessingResponse                                      │
│    • platform_request_id: str (our tracking ID)                  │
│    • status_url: str (check progress)                            │
│    • api_endpoints: Dict[str,str] (REST API URLs)                │
│    • data_characteristics: Dict (bbox, features, size)           │
│                                                                   │
│  Key Principle: Platform doesn't enforce client data models      │
│    - Accepts Dataset→Resource→Version as optional context        │
│    - Works with ANY identifier scheme                            │
│    - Client manages metadata, we manage data processing          │
└─────────────────────────┬────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│                   LAYER 2: COREMACHINE                            │
│              (Universal Job Orchestration Engine)                 │
│                                                                   │
│  Size: 450 lines (vs BaseController God Class: 2,290 lines)      │
│        80% reduction through composition!                         │
│                                                                   │
│  Pattern: Composition over Inheritance                           │
│    ✅ All dependencies INJECTED (not created)                     │
│    ✅ All work DELEGATED (to specialized components)             │
│    ✅ ZERO hard-coded dependencies                               │
│                                                                   │
│  What CoreMachine DOES:                                          │
│    ✅ Coordinate workflow execution                              │
│    ✅ Route messages to appropriate handlers                     │
│    ✅ Manage stage advancement timing                            │
│    ✅ Choose optimal queue strategy (batch vs individual)        │
│                                                                   │
│  What CoreMachine DOES NOT DO:                                   │
│    ❌ Database operations → StateManager                         │
│    ❌ Task creation → OrchestrationManager                       │
│    ❌ Parameter validation → Workflow instances                  │
│    ❌ Business logic → Task handlers                             │
│    ❌ Queue communication → Repository abstractions              │
│                                                                   │
│  Analogy: CoreMachine is the conductor, not the orchestra!       │
└─────────────────────────┬────────────────────────────────────────┘
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
    ┌──────────────────┐    ┌──────────────────┐
    │  StateManager    │    │ Orchestration    │
    │                  │    │   Manager        │
    │ • create_job()   │    │ • create_tasks() │
    │ • create_tasks() │    │ • batch_tasks()  │
    │ • complete_task()│    │ • fan_out()      │
    │ • advance_stage()│    │                  │
    │ • complete_job() │    │                  │
    │                  │    │                  │
    │ Uses PostgreSQL  │    │ Dynamic task     │
    │ advisory locks   │    │ generation       │
    │ for "last task   │    │ (1 → N pattern)  │
    │ turns out lights"│    │                  │
    └──────────────────┘    └──────────────────┘
```

---

## 🎯 Key Design Principles

### 1. Platform Agnosticism
The Platform layer **does not enforce** any specific data organization model:
- ✅ Data Catalog can use Dataset → Resource → Version
- ✅ Analytics apps can use Project → Analysis → Run
- ✅ Mobile apps can use App → Layer → Version
- ✅ Any client can use their own identifier scheme

**Platform accepts identifiers as key-value pairs**, allowing complete flexibility.

### 2. Client Owns Metadata, Platform Owns Processing
**Clear separation of concerns**:

| Client Responsibility | Platform Responsibility |
|----------------------|------------------------|
| Descriptions, tags   | Data processing        |
| User management      | API provisioning       |
| Permissions          | Endpoint availability  |
| Discovery/search     | Format conversion      |
| Metadata cataloging  | Performance optimization |

### 3. Composition Over Inheritance (CoreMachine)
**God Class Anti-Pattern** (BaseController - DEPRECATED):
```python
class BaseController:  # 2,290 lines!
    def __init__(self):
        # Creates everything internally = tight coupling
        self.db_repo = PostgreSQLRepository()
        self.queue_repo = QueueRepository()
        # ... 30+ more dependencies
```

**CoreMachine Pattern** (CURRENT):
```python
class CoreMachine:  # 450 lines
    def __init__(self,
                 all_jobs: Dict,           # INJECTED
                 all_handlers: Dict,       # INJECTED
                 state_manager: StateManager,  # INJECTED
                 config: AppConfig):       # INJECTED
        # NO internal object creation = loose coupling
        self.jobs = all_jobs
        self.handlers = all_handlers
        self.state = state_manager
        self.config = config
```

**Result**: CoreMachine has **ZERO hard dependencies**! All components are swappable.

---

## 📊 Platform Integration Pattern: Data Catalog Example

### Data Catalog's Internal Model
```python
class CatalogDataset:
    dataset_id: str
    title: str
    description: str
    owner: User
    resources: List[CatalogResource]

class CatalogResource:
    resource_id: str
    resource_type: str  # "vector", "raster", etc.
    versions: List[CatalogVersion]

class CatalogVersion:
    version_id: str
    upload_date: datetime
    file_url: str  # Points to raw data in Bronze storage
    api_endpoints: Dict[str, str]  # Filled by Platform!
```

### Catalog Submits Processing Request to Platform
```python
# Catalog calls Platform API
response = requests.post(
    "https://platform-api/process",
    json={
        "client_id": "data_catalog",
        "client_request_id": f"{dataset_id}_{resource_id}_{version_id}",
        "identifiers": {
            "dataset_id": dataset_id,
            "resource_id": resource_id,
            "version_id": version_id
        },
        "data_type": "vector",
        "source_location": catalog_version.file_url,
        "processing_options": {
            "format": "geojson",
            "target_crs": "EPSG:4326"
        },
        "api_type": "ogc",
        "callback_url": "https://catalog-api/platform-callback"
    }
)

# Platform responds immediately
{
    "platform_request_id": "plt_abc123",
    "status": "accepted",
    "status_url": "https://platform-api/status/plt_abc123"
}
```

### Platform Processes Data (via CoreMachine)
1. **Platform receives request** → Creates internal job
2. **CoreMachine processes job** → Stages, tasks, handlers
3. **Data processed** → Vector ingested to PostGIS, STAC created
4. **Platform provisions API** → OGC Features endpoint created
5. **Platform calls back** → Notifies Catalog with endpoints

### Catalog Receives Completion Callback
```python
# Platform sends to catalog_version.callback_url
{
    "platform_request_id": "plt_abc123",
    "client_request_id": "dataset123_resource456_version789",
    "status": "completed",
    "api_endpoints": {
        "features": "https://api/ogc/features/collections/dataset123_resource456_v789",
        "tiles": "https://api/tiles/{z}/{x}/{y}?collection=dataset123_resource456_v789",
        "download": "https://api/download/dataset123_resource456_v789.gpkg"
    },
    "data_characteristics": {
        "feature_count": 10000,
        "bbox": [-180, -90, 180, 90],
        "crs": "EPSG:4326",
        "file_size_mb": 25.4,
        "processing_time_seconds": 45
    }
}
```

### Catalog Updates Its Model
```python
# Catalog stores endpoints in its own database
catalog_version.api_endpoints = response["api_endpoints"]
catalog_version.processing_metadata = response["data_characteristics"]
catalog_version.status = "ready"
catalog_version.save()

# Now users can discover and access via Catalog's UI
# Platform just provides the working endpoints
```

---

## 🔧 CoreMachine Component Breakdown

### Component 1: StateManager
**File**: `core/state_manager.py` (~540 lines)
**Responsibility**: All database operations

**Key Methods**:
```python
state.create_job(job_id, job_type, params)
state.create_tasks(task_definitions)
state.complete_task_and_check_stage(task_id, job_id, stage)  # ← Advisory locks!
state.advance_job_stage(job_id, next_stage, results)
state.complete_job(job_id, final_results)
state.get_job(job_id)
state.get_tasks_for_stage(job_id, stage)
```

**Critical Feature**: PostgreSQL advisory locks for atomic "last task turns out lights" detection.

### Component 2: OrchestrationManager
**File**: `core/orchestration_manager.py` (~400 lines)
**Responsibility**: Dynamic task creation and batching

**Key Methods**:
```python
orchestration.create_tasks_for_stage(
    job_id=job_id,
    stage_num=stage,
    workflow=workflow,
    params=params
)
# Returns: List[TaskDefinition]

orchestration.prepare_batch_tasks(tasks)
# Returns: Batches ready for Service Bus
```

**Critical Feature**: Handles "fan-out" pattern where 1 task creates N tasks (e.g., 1 raster → 204 tiles).

### Component 3: Workflow Registry
**File**: `jobs/registry.py`
**Responsibility**: Job type → Workflow mapping

**Pattern**:
```python
ALL_JOBS = {
    "hello_world": HelloWorldWorkflow,
    "process_large_raster": ProcessLargeRasterWorkflow,
    "container_list": ContainerListWorkflow,
    # ... all job types
}

# CoreMachine receives this dict at initialization
machine = CoreMachine(all_jobs=ALL_JOBS, ...)
```

### Component 4: Handler Registry
**File**: `services/registry.py`
**Responsibility**: Task type → Handler mapping

**Pattern**:
```python
ALL_HANDLERS = {
    "hello_world_greeting": generate_greeting,
    "tiling_scheme": generate_tiling_scheme,
    "tile_extraction": extract_tile,
    "create_cog": create_cog,
    # ... all task handlers
}

# CoreMachine receives this dict at initialization
machine = CoreMachine(all_handlers=ALL_HANDLERS, ...)
```

---

## 📈 Size Comparison: God Class vs CoreMachine

### BaseController (God Class - DEPRECATED)
- **Lines**: 2,290
- **Methods**: 34
- **Pattern**: Inheritance-based
- **Dependencies**: Created internally (tight coupling)
- **Testability**: Poor (can't mock dependencies)
- **Reusability**: Low (job-specific code mixed with generic)

### CoreMachine (Coordinator - CURRENT)
- **Lines**: 450 (80% reduction!)
- **Methods**: 6 core methods
- **Pattern**: Composition-based
- **Dependencies**: Injected (loose coupling)
- **Testability**: Excellent (all dependencies mockable)
- **Reusability**: High (zero job-specific code)

**Key Difference**: BaseController **does everything**. CoreMachine **coordinates everything**.

---

## 🚀 Real-World Workflow: Large Raster Processing

### Platform Request
```json
{
  "client_id": "data_catalog",
  "identifiers": {"dataset_id": "ds_123", "resource_id": "rs_456"},
  "data_type": "raster",
  "source_location": "bronze/17apr2024wv2.tif",
  "processing_options": {
    "target_crs": "EPSG:4326",
    "cog_tier": "analysis",
    "tile_size": 4096
  }
}
```

### CoreMachine Execution (4 Stages)

**Stage 1: Tiling Scheme Generation**
- 1 task: Analyze 18 GB raster, create tiling scheme
- Output: 204-tile grid (GeoJSON)

**Stage 2: Tile Extraction (Fan-Out)**
- 204 tasks: Extract each tile using windowed reads
- Pattern: 1 task → 204 parallel tasks
- Output: 204 individual GeoTIFF tiles in Silver container

**Stage 3: COG Conversion (Parallel Processing)**
- 204 tasks: Convert each tile to Cloud Optimized GeoTIFF
- **NEW**: /vsimem/ in-memory pattern (30-40% faster!)
  - Download tile → /vsimem/ → Process → /vsimem/ → Upload
  - Zero /tmp disk usage
  - Memory cleanup via gdal.Unlink()
- Output: 204 COG tiles optimized for web serving

**Stage 4: MosaicJSON + STAC**
- 1 task: Create MosaicJSON for seamless tile access
- 1 task: Generate STAC metadata for discovery
- Output: Unified API endpoints

### Platform Response
```json
{
  "status": "completed",
  "api_endpoints": {
    "tiles": "https://api/tiles/{z}/{x}/{y}?mosaic=17apr2024wv2",
    "stac": "https://api/stac/collections/17apr2024wv2",
    "cog_tiles": "https://storage/silver/cogs/17apr2024wv2/"
  },
  "data_characteristics": {
    "tile_count": 204,
    "total_size_gb": 18.2,
    "processing_time_minutes": 45,
    "crs": "EPSG:4326",
    "bbox": [...]
  }
}
```

---

## 🎓 Key Takeaways for Future Claudes

1. **Platform Layer** = Client-agnostic REST API for data processing
   - Accepts flexible identifiers from any client
   - Returns API endpoints + metadata
   - Client manages metadata, Platform manages processing

2. **CoreMachine Layer** = Universal orchestration via composition
   - 80% smaller than God Class (450 vs 2,290 lines)
   - Zero hard dependencies (all injected)
   - Delegates ALL work to specialized components

3. **Why Two Layers?**
   - **Platform**: External API for multiple clients
   - **CoreMachine**: Internal orchestration engine
   - **Separation**: Clean public API vs implementation details

4. **Pattern Evolution**:
   - OLD: BaseController God Class (inheritance hell)
   - NEW: CoreMachine Coordinator (composition over inheritance)

5. **Performance Optimization** (26 OCT 2025):
   - Stage 3 COG conversion now uses /vsimem/ pattern
   - 30-40% faster than previous /vsiaz/ approach
   - Zero /tmp disk usage (critical for Azure Functions)
   - Memory leak prevention via gdal.Unlink() cleanup

**Core Principle**: "Give me data, I'll give you API endpoints" - Platform abstracts ALL the complexity.

---

**Last Updated**: 26 OCT 2025
**Related Docs**:
- `docs/architecture/COREMACHINE_DESIGN.md` - Detailed CoreMachine design rationale
- `docs_claude/PLATFORM_SERVICE_ARCHITECTURE.md` - Platform layer specifications
- `docs_claude/PLATFORM_ENTITIES_PATTERNS.md` - Platform data model patterns
- `core/machine.py` - CoreMachine implementation (450 lines)