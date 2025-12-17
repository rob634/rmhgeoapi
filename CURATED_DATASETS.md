# Curated Datasets System

**Status**: Substantially Complete
**Created**: 17 DEC 2025
**Last Updated**: 17 DEC 2025

---

## Overview

Curated datasets are **system-managed geospatial data** that update automatically from external authoritative sources. Unlike user-submitted data, curated datasets:

- Cannot be deleted/modified via normal API
- Update on a schedule (or manually triggered)
- Use `curated_` table prefix for protection
- Track update history and source versions
- Are registered in `app.curated_datasets` registry

**Primary Use Cases**:
- WDPA (World Database on Protected Areas) - Monthly updates from IBAT API
- Admin0 Country Boundaries - Manual updates from Natural Earth
- Other authoritative reference datasets

---

## Architecture

```
                       ┌─────────────────────────────────────┐
                       │         Timer: 2 AM UTC             │
                       │   curated_dataset_scheduler         │
                       └───────────────┬─────────────────────┘
                                       │ checks due datasets
                                       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  app.curated_datasets (Registry Table)                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │ dataset_id │ source_url      │ job_type            │ target_table   │ │
│  ├────────────┼─────────────────┼─────────────────────┼────────────────┤ │
│  │ wdpa       │ ibat-alliance   │ curated_dataset_... │ curated_wdpa   │ │
│  │ admin0     │ naturalearthdata│ curated_dataset_... │ curated_admin0 │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────┘
                                       │ submits job
                                       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  CuratedDatasetUpdateJob (4 Stages)                                      │
│                                                                          │
│  Stage 1: curated_check_source   → Check API for new version            │
│  Stage 2: curated_fetch_data     → Download data file                   │
│  Stage 3: curated_etl_process    → Extract → GeoDataFrame → PostGIS     │
│  Stage 4: curated_finalize       → Update registry, log results         │
└──────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  geo.curated_* (PostGIS Tables)                                          │
│  ├── geo.curated_wdpa_protected_areas  (250K+ polygons)                 │
│  ├── geo.curated_admin0                (country boundaries)             │
│  └── geo.curated_*                     (future datasets)                │
└──────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  OGC Features API                                                        │
│  GET /api/features/collections/curated_wdpa_protected_areas/items       │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## File Structure

```
rmhgeoapi/
├── core/models/
│   └── curated.py              # Pydantic models (CuratedDataset, CuratedUpdateLog)
├── infrastructure/
│   └── curated_repository.py   # Database CRUD operations
├── services/curated/
│   ├── __init__.py
│   ├── registry_service.py     # Business logic layer
│   └── wdpa_handler.py         # WDPA-specific handler (IBAT API)
├── jobs/
│   └── curated_update.py       # 4-stage update job + handlers
├── triggers/curated/
│   ├── __init__.py
│   ├── admin.py                # HTTP CRUD endpoints
│   └── scheduler.py            # Daily timer trigger (2 AM UTC)
└── function_app.py             # Route registration (lines 380-630, 2608-2630)
```

---

## Data Models

### CuratedDataset (Registry Entry)

```python
class CuratedDataset(BaseModel):
    # Identity
    dataset_id: str              # Unique slug (e.g., "wdpa", "admin0")
    name: str                    # Display name
    description: Optional[str]

    # Source Configuration
    source_type: CuratedSourceType    # api_bulk_download, api_paginated, manual
    source_url: str                   # Base API URL
    source_config: Dict[str, Any]     # Auth params, pagination config

    # Pipeline Configuration
    job_type: str                     # "curated_dataset_update"
    update_strategy: CuratedUpdateStrategy  # full_replace, upsert
    update_schedule: Optional[str]    # Cron expression (e.g., "0 0 1 * *")
    credential_key: Optional[str]     # Env var name for API credentials

    # Target Configuration
    target_table_name: str            # MUST start with "curated_"
    target_schema: str = "geo"

    # Status Tracking
    enabled: bool = True
    last_checked_at: Optional[datetime]
    last_updated_at: Optional[datetime]
    last_job_id: Optional[str]
    source_version: Optional[str]     # For change detection
```

### CuratedUpdateLog (Audit Trail)

```python
class CuratedUpdateLog(BaseModel):
    log_id: Optional[int]        # Auto-generated
    dataset_id: str
    job_id: str
    update_type: CuratedUpdateType  # scheduled, manual, triggered
    source_version: Optional[str]

    # Record Counts
    records_added: int = 0
    records_updated: int = 0
    records_deleted: int = 0
    records_total: int = 0

    # Status
    status: CuratedUpdateStatus  # started, downloading, processing, completed, failed, skipped
    error_message: Optional[str]

    # Timing
    started_at: datetime
    completed_at: Optional[datetime]
    duration_seconds: Optional[float]
```

### Enums

```python
class CuratedSourceType(str, Enum):
    API_BULK_DOWNLOAD = "api_bulk_download"  # Download full file
    API_PAGINATED = "api_paginated"          # Page through API
    MANUAL = "manual"                         # Manual trigger only

class CuratedUpdateStrategy(str, Enum):
    FULL_REPLACE = "full_replace"  # TRUNCATE + INSERT
    UPSERT = "upsert"              # INSERT ON CONFLICT UPDATE

class CuratedUpdateType(str, Enum):
    SCHEDULED = "scheduled"   # Timer trigger
    MANUAL = "manual"         # HTTP endpoint
    TRIGGERED = "triggered"   # External webhook

class CuratedUpdateStatus(str, Enum):
    STARTED = "started"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"  # No update needed
```

---

## HTTP Endpoints

### Registry CRUD

```bash
# List all curated datasets
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/curated/datasets

# List only enabled datasets
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/curated/datasets?enabled_only=true"

# Get single dataset
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/curated/datasets/wdpa

# Create new dataset
curl -X POST https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/curated/datasets \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "wdpa",
    "name": "World Database on Protected Areas",
    "source_type": "api_bulk_download",
    "source_url": "https://api.ibat-alliance.org/v1/data-downloads",
    "job_type": "curated_dataset_update",
    "update_strategy": "full_replace",
    "update_schedule": "0 0 1 * *",
    "credential_key": "WDPA_AUTH_KEY",
    "target_table_name": "curated_wdpa_protected_areas"
  }'

# Update dataset
curl -X PUT https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/curated/datasets/wdpa \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'

# Delete registry entry (NOT the data table)
curl -X DELETE "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/curated/datasets/wdpa?confirm=yes"
```

### Operations

```bash
# Trigger manual update (TODO: Not yet implemented)
curl -X POST https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/curated/datasets/wdpa/update

# Get update history
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/curated/datasets/wdpa/history?limit=10"

# Enable scheduled updates
curl -X POST https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/curated/datasets/wdpa/enable

# Disable scheduled updates
curl -X POST https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/curated/datasets/wdpa/disable
```

---

## Update Job Pipeline

### CuratedDatasetUpdateJob

Four-stage workflow using JobBaseMixin pattern:

```
Stage 1: CHECK_SOURCE (curated_check_source)
├── Query source API for available versions
├── Compare with stored source_version
├── Determine if update needed
└── Return: needs_update, download_url, source_version

Stage 2: FETCH_DATA (curated_fetch_data)
├── Skip if no update needed (and not force_update)
├── Download data file (ZIP, GeoJSON, Shapefile)
├── Save to temp directory
└── Return: file_path, file_size

Stage 3: ETL_PROCESS (curated_etl_process)
├── Extract ZIP if needed
├── Find data file (GeoJSON > Shapefile > GDB)
├── Load with geopandas
├── TRUNCATE target table (full_replace strategy)
├── Upload to PostGIS
└── Return: records_loaded, table_name

Stage 4: FINALIZE (curated_finalize)
├── Update registry (last_updated_at, source_version)
├── Create update log entry
└── Return: update_logged
```

### Job Parameters

```python
parameters_schema = {
    "dataset_id": {
        "type": "str",
        "required": True,
        "description": "Curated dataset registry ID"
    },
    "update_type": {
        "type": "str",
        "default": "manual",
        "allowed": ["manual", "scheduled", "triggered"]
    },
    "force_update": {
        "type": "bool",
        "default": False,
        "description": "Force update even if source unchanged"
    },
    "dry_run": {
        "type": "bool",
        "default": False,
        "description": "Simulate update without writing data"
    }
}
```

---

## WDPA Handler

The only currently implemented dataset handler. Fetches data from IBAT API.

### Environment Variables

```bash
WDPA_AUTH_KEY=your_ibat_auth_key
WDPA_AUTH_TOKEN=your_ibat_auth_token
```

### IBAT API

- Base URL: `https://api.ibat-alliance.org/v1`
- Endpoint: `/data-downloads`
- Auth: Query params `auth_key` + `auth_token`

### Handler Methods

```python
class WDPAHandler:
    def check_for_updates(self) -> Dict[str, Any]:
        """Query IBAT API for available downloads."""

    def download_dataset(self, download_url: str) -> Dict[str, Any]:
        """Download WDPA data file (streaming for large files)."""

    def extract_and_load(self, file_path: str, target_table: str) -> Dict[str, Any]:
        """Extract ZIP → Load with geopandas → TRUNCATE + INSERT to PostGIS."""
```

---

## Scheduler

Daily timer trigger at 2 AM UTC checks all enabled datasets with schedules.

### Schedule Evaluation (Simplified)

Currently uses basic time-since-last-check logic:

| Schedule Pattern | Interpreted As |
|-----------------|----------------|
| `0 0 1 * *` (monthly) | 28+ days since check |
| `* * 0` or `* * 7` (weekly) | 6+ days since check |
| `0 0 * * *` (daily) | 23+ hours since check |
| Default | 24+ hours since check |

**Future Enhancement**: Full cron expression parsing with `croniter` library.

---

## Database Schema

### app.curated_datasets

```sql
CREATE TABLE IF NOT EXISTS app.curated_datasets (
    dataset_id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    source_type VARCHAR(50) NOT NULL,
    source_url VARCHAR(500) NOT NULL,
    source_config JSONB DEFAULT '{}',
    job_type VARCHAR(50) NOT NULL,
    update_strategy VARCHAR(50) NOT NULL,
    update_schedule VARCHAR(50),
    credential_key VARCHAR(200),
    target_table_name VARCHAR(255) NOT NULL,
    target_schema VARCHAR(50) DEFAULT 'geo',
    enabled BOOLEAN DEFAULT true,
    last_checked_at TIMESTAMPTZ,
    last_updated_at TIMESTAMPTZ,
    last_job_id VARCHAR(64),
    source_version VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT curated_prefix CHECK (target_table_name LIKE 'curated_%')
);
```

### app.curated_update_log

```sql
CREATE TABLE IF NOT EXISTS app.curated_update_log (
    log_id SERIAL PRIMARY KEY,
    dataset_id VARCHAR(64) NOT NULL REFERENCES app.curated_datasets(dataset_id),
    job_id VARCHAR(64) NOT NULL,
    update_type VARCHAR(50) NOT NULL,
    source_version VARCHAR(100),
    records_added INTEGER DEFAULT 0,
    records_updated INTEGER DEFAULT 0,
    records_deleted INTEGER DEFAULT 0,
    records_total INTEGER DEFAULT 0,
    status VARCHAR(50) NOT NULL,
    error_message TEXT,
    started_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ,
    duration_seconds FLOAT
);

CREATE INDEX idx_curated_log_dataset ON app.curated_update_log(dataset_id);
CREATE INDEX idx_curated_log_status ON app.curated_update_log(status);
```

---

## Implementation Status

| Component | Status | Notes |
|-----------|--------|-------|
| Data Models | ✅ Complete | `core/models/curated.py` |
| Repository | ✅ Complete | `infrastructure/curated_repository.py` |
| Registry Service | ✅ Complete | Singleton pattern, full CRUD |
| HTTP Endpoints | ✅ Complete | All routes registered |
| Timer Scheduler | ✅ Complete | 2 AM UTC daily |
| Update Job | ✅ Complete | 4-stage pipeline |
| WDPA Handler | ✅ Complete | IBAT API integration |
| **Manual Update Trigger** | ❌ TODO | Returns placeholder response |
| **Admin0 Handler** | ❌ TODO | Natural Earth integration |
| **Style Integration** | ❌ TODO | See below |

---

## OGC API Styles Integration

**Curated datasets are THE prime use case for OGC API Styles.**

### Why?

- WDPA has natural category-based styling (IUCN categories: Ia, Ib, II, III, IV, V, VI)
- Admin0 needs consistent boundary styling
- Each curated dataset should have a default style created on ETL

### Integration Point

Add style creation to `curated_etl_process` handler after PostGIS load:

```python
# In services/curated/wdpa_handler.py extract_and_load()

# After successful PostGIS upload:
from ogc_features.repository import OGCFeaturesRepository

repo = OGCFeaturesRepository()

# Create default WDPA style with IUCN category coloring
wdpa_style = {
    "name": "wdpa-iucn-categories",
    "title": "WDPA by IUCN Category",
    "stylingRules": [
        {
            "name": "category-ia",
            "selector": {"op": "=", "args": [{"property": "iucn_cat"}, "Ia"]},
            "symbolizer": {
                "type": "Polygon",
                "fill": {"color": "#1a9850", "opacity": 0.7},
                "stroke": {"color": "#0d5c2e", "width": 1.5}
            }
        },
        # ... more categories ...
        {
            "name": "fallback",
            "symbolizer": {
                "type": "Polygon",
                "fill": {"color": "#cccccc", "opacity": 0.5},
                "stroke": {"color": "#999999", "width": 1}
            }
        }
    ]
}

repo.create_style(
    collection_id="curated_wdpa_protected_areas",
    style_id="iucn-categories",
    style_spec=wdpa_style,
    title="IUCN Categories",
    is_default=True
)
```

### Data Flow with Styles

```
IBAT API → Download → PostGIS Table → OGC Features API
                           │
                           ▼
                    Style Created → OGC Styles API
                           │
                           ▼
              GET /features/collections/curated_wdpa/styles/iucn-categories?f=leaflet
                           │
                           ▼
                    Leaflet Map with Category Colors
```

---

## Adding New Curated Datasets

### Step 1: Create Dataset Handler

```python
# services/curated/admin0_handler.py

class Admin0Handler:
    """Handler for Natural Earth Admin0 boundaries."""

    def check_for_updates(self) -> Dict[str, Any]:
        """Check Natural Earth for new release."""
        # Natural Earth uses versioned releases
        pass

    def download_dataset(self, download_url: str) -> Dict[str, Any]:
        """Download shapefile from Natural Earth."""
        pass

    def extract_and_load(self, file_path: str, ...) -> Dict[str, Any]:
        """Load to geo.curated_admin0."""
        pass
```

### Step 2: Register in Job Handler

Update `jobs/curated_update.py` to route to new handler:

```python
def curated_check_source(params: Dict[str, Any], ...) -> Dict[str, Any]:
    dataset_id = params.get('dataset_id')

    if dataset_id == "wdpa":
        from services.curated.wdpa_handler import WDPAHandler
        handler = WDPAHandler()
    elif dataset_id == "admin0":
        from services.curated.admin0_handler import Admin0Handler
        handler = Admin0Handler()
    else:
        # Generic handler
        ...
```

### Step 3: Create Registry Entry

```bash
curl -X POST .../api/curated/datasets \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "admin0",
    "name": "Admin0 Country Boundaries",
    "source_type": "manual",
    "source_url": "https://www.naturalearthdata.com/",
    "job_type": "curated_dataset_update",
    "update_strategy": "full_replace",
    "update_schedule": null,
    "target_table_name": "curated_admin0"
  }'
```

---

## TODO

1. **Implement Manual Update Trigger** - Connect `_trigger_update()` to CoreMachine job submission
2. **Add Admin0 Handler** - Natural Earth integration
3. **Full Cron Parsing** - Use `croniter` for proper schedule evaluation
4. **Style Integration** - Auto-create styles on ETL (after OGC API Styles implementation)
5. **Change Detection** - Compare source_version to skip unnecessary downloads
6. **Cleanup Handler** - Delete old temp files after successful update

---

## Related Documentation

| Document | Purpose |
|----------|---------|
| `STYLE_IMPLEMENTATION.md` | OGC API Styles (integrates with curated datasets) |
| `docs_claude/ARCHITECTURE_REFERENCE.md` | Overall system architecture |
| `docs_claude/JOB_CREATION_QUICKSTART.md` | JobBaseMixin pattern reference |
