# God Objects Explained - Detailed Refactoring Guide

**Date**: 18 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Detailed explanation of the two high-priority god objects and refactoring strategies

---

## Executive Summary

Two files require urgent refactoring due to god object anti-pattern:

1. **function_app.py** (2,208 lines) - **78 HTTP routes + 2 queue triggers** in single file
2. **config.py** (1,747 lines) - **AppConfig class with 63+ fields** covering 6 different domains

Both violate Single Responsibility Principle and cause real development pain.

---

## 1. function_app.py - The Monolithic Entry Point

### Current State: 2,208 Lines, 80 Functions

**Line breakdown**:
```
Lines 1-329:     Imports, initialization, CoreMachine setup
Lines 330-1724:  78 HTTP route handlers (1,394 lines!)
Lines 1725-end:  2 Service Bus queue processors
```

**Route distribution by domain**:
```bash
# Database Admin API (29 routes) - Lines 336-641
@app.route(route="dbadmin/schemas", ...)              # 17 schema/table inspection
@app.route(route="dbadmin/queries/running", ...)      # 4 query monitoring
@app.route(route="dbadmin/health", ...)               # 2 health checks
@app.route(route="dbadmin/maintenance/nuke", ...)     # 3 maintenance (NUCLEAR!)
@app.route(route="dbadmin/diagnostics/enums", ...)    # 3 diagnostics

# Service Bus Monitoring (6 routes) - Lines 501-549
@app.route(route="servicebus/queues", ...)            # 2 queue listing
@app.route(route="servicebus/queues/{name}/peek", ...)  # 3 queue inspection
@app.route(route="servicebus/health", ...)            # 1 health check

# CoreMachine API (2 routes) - Lines 551-565
@app.route(route="jobs/submit/{job_type}", ...)       # Job submission
@app.route(route="jobs/status/{job_id}", ...)         # Job status

# CoreMachine Debug (4 routes) - Lines 567-615
@app.route(route="dbadmin/jobs", ...)                 # Job queries
@app.route(route="dbadmin/tasks/{job_id}", ...)       # Task queries

# Platform API (4 routes) - Lines 592-615
@app.route(route="dbadmin/platform/requests", ...)    # Platform request queries
@app.route(route="dbadmin/platform/orchestration", ...) # Orchestration queries

# Analysis/Debug (2 routes) - Lines 642-696
@app.route(route="h3/debug", ...)                     # H3 debugging
@app.route(route="analysis/container/{job_id}", ...)  # Container analysis

# Platform Layer (21 routes) - Lines 733-1220
POST /api/platform/submit                             # Main platform submission
GET  /api/platform/status/{request_id}                # Platform status
... 19 more platform endpoints

# STAC API v1.0 (6 routes) - Lines 1221-1355
GET /api/stac                                         # Landing page
GET /api/stac/conformance                             # Conformance classes
GET /api/stac/collections                             # Collections list
GET /api/stac/collections/{collection_id}             # Collection detail
GET /api/stac/collections/{collection_id}/items       # Items list (paginated)
GET /api/stac/collections/{collection_id}/items/{item_id}  # Item detail

# TiTiler Integration (1 route) - Lines 1356-1479
GET /api/search                                       # TiTiler-PgSTAC search

# OGC Features API (6 routes) - Lines 1481-1555
GET /api/features                                     # Landing page
GET /api/features/conformance                         # Conformance classes
GET /api/features/collections                         # Collections list (PostGIS tables)
GET /api/features/collections/{collection_id}         # Collection metadata
GET /api/features/collections/{collection_id}/items   # Features query (bbox, pagination)
GET /api/features/collections/{collection_id}/items/{feature_id}  # Single feature

# Additional Routes (4 routes) - Lines 1558-1724
GET /api/vector/viewer                                # Vector map viewer
GET /api/interface/{name}                             # Web interfaces
POST /api/jobs/ingest_vector                          # Direct vector ingest
POST /api/test/create-rasters                         # Test endpoint
GET /api/dbadmin/debug/all                            # Debug aggregator

# Queue Processors (2 triggers) - Lines 1856-2208
Service Bus: geospatial-jobs queue                    # CoreMachine job processor
Service Bus: geospatial-tasks queue                   # CoreMachine task processor
```

---

### Why This Is a Problem

#### **1. Violation of Single Responsibility Principle**

function_app.py handles **6 completely different domains**:

| Domain | Routes | Purpose | Team Ownership |
|--------|--------|---------|----------------|
| **Database Admin** | 29 | Dev/QA debugging (remove for UAT!) | Infrastructure team |
| **Service Bus Monitor** | 6 | Queue health monitoring | Infrastructure team |
| **CoreMachine** | 6 | Job orchestration API | Platform team |
| **Platform Layer** | 21 | Platform-as-a-Service API | Platform team |
| **STAC API** | 6 | STAC v1.0.0 metadata catalog | Catalog team |
| **OGC Features** | 6 | OGC API - Features Core 1.0 | Geospatial team |
| **Misc/Debug** | 4 | Testing and debugging | Various |

**Each domain should be in its own file!**

---

#### **2. Development Pain Points**

##### **A. Navigation Nightmare**
```bash
# Developer scenario: "Where's the STAC collections endpoint?"
# Current: Search through 2,208 lines
# Better: Look in stac_api/triggers.py (150 lines)

# Current:
$ grep -n "stac/collections" function_app.py
1570:@app.route(route="stac/collections", methods=["GET"])
# Line 1570... scroll, scroll, scroll...

# With refactoring:
$ cat stac_api/triggers.py  # Only 150 lines, find it in 5 seconds
```

##### **B. Merge Conflicts**
```bash
# Scenario: Two developers working on different APIs

# Developer A: Adding new STAC endpoint (working on lines 1300-1400)
# Developer B: Adding new OGC endpoint (working on lines 1500-1600)

# Current problem:
# Both editing function_app.py → MERGE CONFLICT!

# After refactoring:
# Developer A: Editing stac_api/triggers.py
# Developer B: Editing ogc_features/triggers.py
# NO CONFLICT - different files!
```

##### **C. Testing Complexity**
```python
# Current: Can't test STAC API without loading all 80 routes
def test_stac_endpoints():
    # Must import entire function_app.py
    from function_app import app
    # Now you've loaded:
    # - 29 database admin routes
    # - 6 service bus routes
    # - 21 platform routes
    # - 6 OGC routes
    # - All 80 routes just to test 6 STAC endpoints!

# After refactoring: Test STAC in isolation
def test_stac_endpoints():
    from stac_api.triggers import register_stac_routes
    test_app = FunctionApp()
    register_stac_routes(test_app)
    # Only 6 STAC routes loaded - fast, focused testing!
```

##### **D. Security Risk**
```python
# Lines 336-641: Database Admin API
# Comment: "⚠️ FCO (For Claude Only) - Keep for QA, remove before UAT"
# Comment: "🚫 PRODUCTION: REMOVE - Security risk"

# Current problem:
# 29 dangerous endpoints mixed with production code
# Easy to forget to remove before UAT deployment!

# After refactoring:
# triggers/dbadmin_triggers.py (separate file)
# Before UAT: Just delete the file, don't register the routes
# Crystal clear: "If dbadmin_triggers.py exists, we forgot to remove it!"
```

---

### Refactoring Strategy for function_app.py

#### **Target Structure**

```python
# function_app.py (200 lines) - Initialization only
from azure.functions import FunctionApp
from config import get_config
from core.machine import CoreMachine
from jobs import ALL_JOBS
from services import ALL_HANDLERS

# Initialize CoreMachine
core_machine = CoreMachine(
    all_jobs=ALL_JOBS,
    all_handlers=ALL_HANDLERS
)

# Initialize Azure Functions app
app = FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# Register routes by domain
from triggers.coremachine_triggers import register_coremachine_routes
from triggers.platform_triggers import register_platform_routes
from stac_api.triggers import register_stac_routes  # Already exists!
from ogc_features.triggers import register_ogc_routes  # Already exists!

register_coremachine_routes(app, core_machine)
register_platform_routes(app, core_machine)
register_stac_routes(app)
register_ogc_routes(app)

# DEV/QA ONLY - Comment out before UAT deployment
# from triggers.dbadmin_triggers import register_dbadmin_routes
# from triggers.servicebus_triggers import register_servicebus_routes
# register_dbadmin_routes(app)
# register_servicebus_triggers(app)
```

#### **New Module: triggers/coremachine_triggers.py** (300 lines)

```python
"""CoreMachine HTTP API triggers - Job submission and status."""

import azure.functions as func
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.machine import CoreMachine

def register_coremachine_routes(app: func.FunctionApp, core_machine: 'CoreMachine'):
    """Register CoreMachine API routes."""

    @app.route(route="jobs/submit/{job_type}", methods=["POST"])
    def submit_job(req: func.HttpRequest) -> func.HttpResponse:
        """Submit job to CoreMachine orchestrator."""
        job_type = req.route_params.get('job_type')
        # ... implementation (currently lines 551-557 in function_app.py)
        return func.HttpResponse(...)

    @app.route(route="jobs/status/{job_id}", methods=["GET"])
    def get_job_status(req: func.HttpRequest) -> func.HttpResponse:
        """Get job status from CoreMachine."""
        job_id = req.route_params.get('job_id')
        # ... implementation (currently lines 558-565 in function_app.py)
        return func.HttpResponse(...)

    # Debug endpoints (DEV/QA only)
    @app.route(route="dbadmin/jobs", methods=["GET"])
    def query_jobs(req: func.HttpRequest) -> func.HttpResponse:
        """Query jobs with filters (DEV/QA only)."""
        # ... implementation (currently lines 567-572 in function_app.py)
        return func.HttpResponse(...)

    @app.route(route="dbadmin/tasks/{job_id}", methods=["GET"])
    def query_tasks(req: func.HttpRequest) -> func.HttpResponse:
        """Query tasks for job (DEV/QA only)."""
        # ... implementation (currently lines 579-591 in function_app.py)
        return func.HttpResponse(...)

    # Queue processors
    @app.service_bus_queue_trigger(
        arg_name="msg",
        queue_name="geospatial-jobs",
        connection="ServiceBusConnection"
    )
    def process_jobs_queue(msg: func.ServiceBusMessage):
        """Process job messages from Service Bus."""
        # ... implementation (currently lines 1856-1950 in function_app.py)
        pass

    @app.service_bus_queue_trigger(
        arg_name="msg",
        queue_name="geospatial-tasks",
        connection="ServiceBusConnection"
    )
    def process_tasks_queue(msg: func.ServiceBusMessage):
        """Process task messages from Service Bus."""
        # ... implementation (currently lines 1967-2208 in function_app.py)
        pass
```

#### **New Module: triggers/dbadmin_triggers.py** (500 lines)

```python
"""
Database Admin API triggers - DEV/QA ONLY.

⚠️ SECURITY WARNING:
These endpoints expose sensitive database internals and MUST be removed
before UAT/Production deployment.

Removal checklist:
1. Delete this file (triggers/dbadmin_triggers.py)
2. Comment out registration in function_app.py
3. Verify removed: curl https://<app>/api/dbadmin/schemas → 404

Production replacement:
- Use Azure Log Analytics (KQL queries on app_jobs, app_tasks)
- Use Azure Portal for database monitoring
- Use Application Insights for trace logs
"""

import azure.functions as func

def register_dbadmin_routes(app: func.FunctionApp):
    """
    Register database admin routes (DEV/QA ONLY).

    DO NOT call this function in UAT or Production environments!
    """

    # Schema inspection (17 routes) - Lines 366-448 in function_app.py
    @app.route(route="dbadmin/schemas", methods=["GET"])
    def list_schemas(req: func.HttpRequest) -> func.HttpResponse:
        """List all database schemas."""
        # ... move implementation from function_app.py line 366
        pass

    # ... 28 more dbadmin routes

    # Nuclear maintenance (3 routes) - DANGEROUS!
    @app.route(route="dbadmin/maintenance/nuke", methods=["POST"])
    def nuke_schema(req: func.HttpRequest) -> func.HttpResponse:
        """
        ☢️ NUCLEAR OPTION: Drop all schema objects.

        Requires ?confirm=yes query parameter.
        DEV ONLY - DO NOT deploy to production!
        """
        # ... move implementation from function_app.py line 452
        pass
```

#### **Benefits of Refactoring function_app.py**

| Benefit | Current (Monolith) | After Refactoring |
|---------|-------------------|-------------------|
| **File size** | 2,208 lines | 200 lines (function_app.py) |
| **Find STAC endpoint** | Search 2,208 lines | Look in stac_api/triggers.py (150 lines) |
| **Merge conflicts** | High (everyone edits same file) | Low (different domains = different files) |
| **Testing** | All 80 routes load | Test each domain independently |
| **Security risk** | Admin endpoints mixed with production | Clear separation: delete dbadmin_triggers.py before UAT |
| **Team ownership** | Unclear | stac_api/ = Catalog team, ogc_features/ = Geospatial team |

#### **Migration Steps** (4-6 hours)

1. **Create trigger modules** (2 hours)
   ```bash
   mkdir -p triggers
   touch triggers/__init__.py
   touch triggers/coremachine_triggers.py
   touch triggers/platform_triggers.py
   touch triggers/dbadmin_triggers.py
   touch triggers/servicebus_triggers.py
   ```

2. **Move routes to modules** (2 hours)
   - Copy route handlers from function_app.py
   - Wrap in `register_*_routes(app)` functions
   - Test each module independently

3. **Update function_app.py** (30 min)
   - Keep initialization code only
   - Add registration calls
   - Remove moved routes

4. **Test all endpoints** (1 hour)
   - Verify all 80 routes still work
   - Test queue processors
   - Check health endpoint

5. **Update stac_api/triggers.py and ogc_features/triggers.py** (30 min)
   - These files already exist but don't export `register_*_routes()` function
   - Add wrapper functions for consistency

---

## 2. config.py - The Configuration Monster

### Current State: 1,747 Lines, AppConfig Has 63+ Fields

**File breakdown**:
```
Lines 1-58:      Imports
Lines 59-254:    COG tier enums and profiles (CogTier, CogTierProfile, etc.)
Lines 255-299:   COG tier utility functions
Lines 300-364:   StorageAccountConfig class
Lines 365-495:   MultiAccountStorageConfig class
Lines 496-1586:  AppConfig class (1,090 lines!! 🔴)
Lines 1587-1621: get_config() singleton factory
Lines 1622-1631: QueueNames constants
Lines 1632-1747: debug_config(), get_postgres_connection_string()
```

**AppConfig class sections** (63+ fields across 6 domains):

```python
class AppConfig(BaseModel):
    """1,090 lines of configuration fields!"""

    # ======================================================================
    # Multi-Account Storage Configuration (NEW - 29 OCT 2025)
    # ======================================================================
    storage: MultiAccountStorageConfig          # 1 field (complex nested)

    # ======================================================================
    # Azure Storage Configuration (DEPRECATED - 4 fields)
    # ======================================================================
    storage_account_name: str
    bronze_container_name: str
    silver_container_name: str
    gold_container_name: str

    # ======================================================================
    # Vector ETL Configuration (2 fields)
    # ======================================================================
    vector_pickle_container: str
    vector_pickle_prefix: str

    # ======================================================================
    # Raster Pipeline Configuration (15+ fields)
    # ======================================================================
    intermediate_tiles_container: Optional[str]
    raster_intermediate_prefix: str
    raster_size_threshold_mb: int
    raster_cog_compression: str
    raster_cog_jpeg_quality: int
    raster_cog_tile_size: int
    raster_overview_resampling: str
    raster_target_crs: str
    raster_reproject_resampling: str
    raster_strict_validation: bool
    raster_cog_in_memory: bool
    raster_mosaicjson_maxzoom: int
    # ... 3+ more raster fields

    # ======================================================================
    # PostgreSQL/PostGIS Configuration (10+ fields)
    # ======================================================================
    postgis_host: str
    postgis_port: int
    postgis_user: str
    postgis_password: Optional[str]
    postgis_database: str
    postgis_schema: str
    app_schema: str
    use_managed_identity: bool
    managed_identity_name: Optional[str]
    # ... more DB fields

    # ======================================================================
    # STAC Configuration (5+ fields)
    # ======================================================================
    stac_default_collection: str
    # ... STAC metadata fields

    # ======================================================================
    # Service Bus Configuration (5+ fields)
    # ======================================================================
    # ... Service Bus connection strings, queue names

    # ======================================================================
    # Application Settings (10+ fields)
    # ======================================================================
    debug_mode: bool
    # ... timeouts, retry policies, logging levels

    # ======================================================================
    # H3 Grid Configuration (3+ fields)
    # ======================================================================
    # ... H3 resolution levels, cell counts

    # ======================================================================
    # Key Vault Configuration (3+ fields)
    # ======================================================================
    # ... Key Vault URLs, secret names

    # Plus: 10+ computed properties (@property methods)
    # Plus: 5+ validation methods
    # Plus: 200+ lines of documentation strings
```

---

### Why This Is a Problem

#### **1. Impossible to Find Settings**

```python
# Developer scenario: "What's the COG compression default?"
# Current: Search through 1,747 lines

$ grep -n "cog_compression" config.py
581:    raster_cog_compression: str = Field(

# Line 581... but AppConfig starts at line 496
# So that's... (581 - 496) = 85 lines into AppConfig
# Scroll, scroll, scroll...

# After refactoring:
$ cat config/raster_config.py  # Only 300 lines
# Found in 5 seconds!
```

#### **2. Unclear Dependencies**

```python
# Current: Everything in one class
class AppConfig:
    # Storage config
    storage: MultiAccountStorageConfig

    # But also database config!
    postgis_host: str
    postgis_database: str

    # But also raster config!
    raster_cog_compression: str

    # But also STAC config!
    stac_default_collection: str

    # But also Service Bus config!
    # ...

# Question: "Does the raster pipeline need database access?"
# Current: No idea - AppConfig has everything!
# Answer: Can't tell which configs are actually needed

# After refactoring:
from config.raster_config import RasterConfig
from config.storage_config import StorageConfig

class RasterPipeline:
    def __init__(
        self,
        raster_config: RasterConfig,      # Clear: needs raster settings
        storage_config: StorageConfig     # Clear: needs storage access
        # NO database_config - doesn't need it!
    ):
        pass

# Now it's obvious: Raster pipeline doesn't need database!
```

#### **3. Testing Complexity**

```python
# Current: Must instantiate entire AppConfig to test raster code
def test_raster_cog_creation():
    config = AppConfig.from_environment()  # Loads ALL 63+ fields!
    # But I only need 15 raster fields...
    # Now I have to mock:
    # - Database connection strings (not needed for COG creation)
    # - Service Bus connection strings (not needed)
    # - STAC config (not needed)
    # - H3 config (not needed)
    # All to test COG compression!

# After refactoring: Only load what you need
def test_raster_cog_creation():
    raster_config = RasterConfig(
        compression="deflate",
        tile_size=512,
        # Only 15 raster fields - fast, focused!
    )
    # No database mocking needed
    # No Service Bus mocking needed
    # Just test COG creation!
```

#### **4. Merge Conflicts (Again!)**

```bash
# Scenario: Two developers working on different features

# Developer A: Adding new raster compression option (line 581)
# Developer B: Adding new database timeout setting (line 721)

# Current problem:
# Both editing config.py AppConfig class → MERGE CONFLICT!

# After refactoring:
# Developer A: Editing config/raster_config.py
# Developer B: Editing config/database_config.py
# NO CONFLICT - different files!
```

---

### Refactoring Strategy for config.py

#### **Target Structure**

```python
# config/__init__.py (100 lines) - Main export
from .app_config import AppConfig
from .storage_config import (
    CogTier,
    CogTierProfile,
    StorageConfig,
    determine_applicable_tiers
)
from .database_config import DatabaseConfig, get_postgres_connection_string
from .queue_config import QueueConfig, QueueNames
from .raster_config import RasterConfig
from .vector_config import VectorConfig

def get_config() -> AppConfig:
    """
    Get global application configuration.

    Composes all domain configs into single AppConfig.
    """
    global _config_instance
    if _config_instance is None:
        _config_instance = AppConfig(
            storage=StorageConfig.from_environment(),
            database=DatabaseConfig.from_environment(),
            queues=QueueConfig.from_environment(),
            raster=RasterConfig.from_environment(),
            vector=VectorConfig.from_environment()
        )
    return _config_instance

_config_instance: Optional[AppConfig] = None

def debug_config() -> dict:
    """Debug output with masked passwords."""
    config = get_config()
    return {
        "storage": config.storage.debug_dict(),
        "database": config.database.debug_dict(),  # Masks password
        "queues": config.queues.debug_dict(),
        "raster": config.raster.debug_dict(),
        "vector": config.vector.debug_dict()
    }

__all__ = [
    'AppConfig', 'get_config', 'debug_config',
    'CogTier', 'CogTierProfile', 'StorageConfig',
    'DatabaseConfig', 'QueueConfig', 'RasterConfig', 'VectorConfig',
    'QueueNames', 'get_postgres_connection_string'
]
```

#### **New Module: config/app_config.py** (150 lines)

```python
"""Main application configuration - composes all domain configs."""

from pydantic import BaseModel
from .storage_config import StorageConfig
from .database_config import DatabaseConfig
from .queue_config import QueueConfig
from .raster_config import RasterConfig
from .vector_config import VectorConfig

class AppConfig(BaseModel):
    """
    Application configuration - composition of domain configs.

    Instead of 63+ fields in one class, we compose smaller configs.
    Each domain config is responsible for its own validation and defaults.
    """

    # Core application settings (10 fields max)
    debug_mode: bool = Field(default=False)
    environment: str = Field(default="dev")
    timeout_seconds: int = Field(default=300)
    max_retries: int = Field(default=3)
    log_level: str = Field(default="INFO")
    # ... 5 more app-level settings

    # Domain configurations (composed, not inherited)
    storage: StorageConfig
    database: DatabaseConfig
    queues: QueueConfig
    raster: RasterConfig
    vector: VectorConfig

    # Clean, focused, maintainable!
```

#### **New Module: config/storage_config.py** (400 lines)

```python
"""Azure Storage configuration - COG tiers, multi-account trust zones."""

from enum import Enum
from typing import List
from pydantic import BaseModel, Field

class CogTier(str, Enum):
    """COG output tiers for compression/quality trade-offs."""
    VISUALIZATION = "visualization"  # JPEG, hot storage, 90% reduction
    ANALYSIS = "analysis"            # DEFLATE, hot storage, 75% reduction
    ARCHIVE = "archive"              # LZW, cool storage, 10% reduction

class CogTierProfile(BaseModel):
    """COG tier compression settings."""
    tier: CogTier
    compression: str
    jpeg_quality: Optional[int]
    storage_tier: str
    # ... COG tier details

COG_TIER_PROFILES = {
    CogTier.VISUALIZATION: CogTierProfile(...),
    CogTier.ANALYSIS: CogTierProfile(...),
    CogTier.ARCHIVE: CogTierProfile(...)
}

def determine_applicable_tiers(band_count: int, data_type: str) -> List[CogTier]:
    """Determine which COG tiers are compatible with raster."""
    # ... logic (currently lines 255-299 in config.py)

class StorageAccountConfig(BaseModel):
    """Single Azure Storage account configuration."""
    # ... (currently lines 300-364 in config.py)

class MultiAccountStorageConfig(BaseModel):
    """Multi-account trust zones (Bronze/Silver/SilverExternal)."""
    # ... (currently lines 365-495 in config.py)

class StorageConfig(BaseModel):
    """Azure Storage configuration."""
    storage: MultiAccountStorageConfig

    # Legacy fields (deprecated)
    bronze_container_name: str = Field(deprecated=True)
    silver_container_name: str = Field(deprecated=True)

    @classmethod
    def from_environment(cls):
        """Load from environment variables."""
        return cls(storage=MultiAccountStorageConfig.from_environment())
```

#### **New Module: config/database_config.py** (300 lines)

```python
"""PostgreSQL/PostGIS database configuration."""

from typing import Optional
from pydantic import BaseModel, Field

class DatabaseConfig(BaseModel):
    """PostgreSQL/PostGIS configuration."""

    # Connection settings (6 fields)
    host: str = Field(...)
    port: int = Field(default=5432)
    user: str = Field(...)
    password: Optional[str] = Field(default=None, repr=False)  # Never print!
    database: str = Field(...)

    # Schema settings (3 fields)
    postgis_schema: str = Field(default="geo")
    app_schema: str = Field(default="app")
    platform_schema: str = Field(default="platform")

    # Managed identity (2 fields)
    use_managed_identity: bool = Field(default=True)
    managed_identity_name: Optional[str] = Field(default=None)

    # Connection pooling (4 fields)
    min_connections: int = Field(default=1)
    max_connections: int = Field(default=20)
    connection_timeout_seconds: int = Field(default=30)
    statement_timeout_seconds: int = Field(default=300)

    @property
    def connection_string(self) -> str:
        """Build PostgreSQL connection string."""
        if self.use_managed_identity:
            # Use managed identity (no password)
            return f"host={self.host} port={self.port} dbname={self.database} user={self.user}"
        else:
            # Use password authentication
            return f"host={self.host} port={self.port} dbname={self.database} user={self.user} password={self.password}"

    def debug_dict(self) -> dict:
        """Debug output with masked password."""
        return {
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "user": self.user,
            "password": "***MASKED***" if self.password else None,
            "schemas": {
                "postgis": self.postgis_schema,
                "app": self.app_schema,
                "platform": self.platform_schema
            },
            "managed_identity": self.use_managed_identity
        }

    @classmethod
    def from_environment(cls):
        """Load from environment variables."""
        import os
        return cls(
            host=os.environ["POSTGIS_HOST"],
            port=int(os.environ.get("POSTGIS_PORT", "5432")),
            user=os.environ["POSTGIS_USER"],
            password=os.environ.get("POSTGIS_PASSWORD"),
            database=os.environ["POSTGIS_DATABASE"],
            # ... load all fields from env
        )

def get_postgres_connection_string(config: Optional[DatabaseConfig] = None) -> str:
    """
    Get PostgreSQL connection string.

    Convenience function for legacy code compatibility.
    """
    if config is None:
        from config import get_config
        config = get_config().database

    return config.connection_string
```

#### **New Module: config/raster_config.py** (250 lines)

```python
"""Raster processing pipeline configuration."""

from pydantic import BaseModel, Field

class RasterConfig(BaseModel):
    """Raster processing configuration."""

    # File size thresholds (2 fields)
    size_threshold_mb: int = Field(default=1000, description="Threshold for large file pipeline")

    # COG creation (7 fields)
    cog_compression: str = Field(default="deflate")
    cog_jpeg_quality: int = Field(default=85)
    cog_tile_size: int = Field(default=512)
    cog_in_memory: bool = Field(default=True, description="Use /vsimem/ for COG creation")
    overview_resampling: str = Field(default="average")
    target_crs: str = Field(default="EPSG:4326")
    reproject_resampling: str = Field(default="bilinear")

    # Validation (1 field)
    strict_validation: bool = Field(default=True)

    # MosaicJSON (1 field)
    mosaicjson_maxzoom: int = Field(default=24)

    # Intermediate storage (2 fields)
    intermediate_tiles_container: Optional[str] = Field(default=None)
    intermediate_prefix: str = Field(default="temp/raster_etl")

    @classmethod
    def from_environment(cls):
        """Load from environment variables."""
        import os
        return cls(
            cog_compression=os.environ.get("RASTER_COG_COMPRESSION", "deflate"),
            # ... load all fields
        )
```

#### **New Module: config/vector_config.py** (150 lines)

```python
"""Vector processing pipeline configuration."""

from pydantic import BaseModel, Field

class VectorConfig(BaseModel):
    """Vector processing configuration."""

    # Pickle intermediate storage (2 fields)
    pickle_container: str = Field(default="rmhazuregeotemp")
    pickle_prefix: str = Field(default="temp/vector_etl")

    # Chunk processing (2 fields)
    default_chunk_size: int = Field(default=1000)
    auto_chunk_sizing: bool = Field(default=True)

    # PostGIS ingestion (3 fields)
    target_schema: str = Field(default="geo")
    create_spatial_indexes: bool = Field(default=True)
    create_attribute_indexes: bool = Field(default=False)

    @classmethod
    def from_environment(cls):
        """Load from environment variables."""
        import os
        return cls(
            pickle_container=os.environ.get("VECTOR_PICKLE_CONTAINER", "rmhazuregeotemp"),
            # ... load all fields
        )
```

#### **New Module: config/queue_config.py** (200 lines)

```python
"""Azure Service Bus queue configuration."""

from pydantic import BaseModel, Field

class QueueNames:
    """Queue name constants."""
    JOBS = "geospatial-jobs"
    TASKS = "geospatial-tasks"

class QueueConfig(BaseModel):
    """Service Bus queue configuration."""

    # Connection (1 field)
    connection_string: str = Field(..., repr=False)  # Never print!

    # Queue names (2 fields)
    jobs_queue: str = Field(default=QueueNames.JOBS)
    tasks_queue: str = Field(default=QueueNames.TASKS)

    # Batch processing (3 fields)
    batch_size: int = Field(default=100)
    batch_threshold: int = Field(default=50)
    send_delay_seconds: float = Field(default=0.1)

    # Retry policy (4 fields)
    max_delivery_count: int = Field(default=5)
    message_ttl_seconds: int = Field(default=86400)  # 24 hours
    lock_duration_seconds: int = Field(default=300)  # 5 minutes
    dead_letter_on_max_delivery: bool = Field(default=True)

    @classmethod
    def from_environment(cls):
        """Load from environment variables."""
        import os
        return cls(
            connection_string=os.environ["ServiceBusConnection"],
            # ... load all fields
        )
```

---

### Benefits of Refactoring config.py

| Benefit | Current (Monolith) | After Refactoring |
|---------|-------------------|-------------------|
| **AppConfig size** | 1,090 lines (63+ fields) | 150 lines (5 composed configs) |
| **Find raster setting** | Search 1,747 lines | Look in config/raster_config.py (250 lines) |
| **Test raster code** | Mock all 63+ fields | Only need RasterConfig (15 fields) |
| **Merge conflicts** | High (everyone edits AppConfig) | Low (different domains = different files) |
| **Clear dependencies** | Unclear (everything in one class) | Obvious (import only what you need) |
| **Team ownership** | Unclear | raster_config.py = Raster team, database_config.py = DBA team |

---

## Summary: Why These Are High Priority

### function_app.py Refactoring

**Urgency**: HIGH - Security risk + Developer productivity

**Problems**:
1. 29 dangerous admin endpoints mixed with production code
2. Merge conflicts on every new endpoint
3. Can't test APIs in isolation
4. Hard to find code (2,208 lines to search)

**Benefits**:
1. Easy to remove admin endpoints before UAT (delete one file)
2. Reduced merge conflicts (different files)
3. Better testing (test each API independently)
4. Faster navigation (150-500 line files)

**Effort**: 4-6 hours
**Impact**: HIGH (security + productivity)

---

### config.py Refactoring

**Urgency**: HIGH - Maintainability + Testing

**Problems**:
1. Can't find settings (1,747 lines to search)
2. Unclear dependencies (raster code needs database config?)
3. Testing complexity (mock 63+ fields to test raster code)
4. Merge conflicts on config changes

**Benefits**:
1. Easy to find settings (domain-specific files)
2. Clear dependencies (import only what you need)
3. Simpler testing (mock only domain config)
4. Reduced merge conflicts (different files)

**Effort**: 6-8 hours
**Impact**: HIGH (maintainability + testing)

---

## Conclusion

Both god objects cause real pain:
- **function_app.py**: Security risk + merge conflicts
- **config.py**: Hard to find settings + testing complexity

Refactoring eliminates pain and follows **Single Responsibility Principle**.

**Recommended order**:
1. Refactor function_app.py (4-6 hours) - Higher priority (security)
2. Refactor config.py (6-8 hours) - Medium priority (maintainability)

Total effort: ~12-14 hours spread over 2-3 sessions.
