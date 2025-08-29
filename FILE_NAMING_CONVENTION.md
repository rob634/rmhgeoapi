# File Naming Convention
**Created**: August 29, 2025  
**Purpose**: Define consistent file naming patterns for clean architecture organization  
**Philosophy**: Module prefixes enable clear separation of concerns without folder hierarchy

---

## 🎯 **NAMING PHILOSOPHY**

**Prefix Pattern**: `{module_prefix}_{descriptive_name}.py`

**Benefits**:
- ✅ **Instant Recognition**: File purpose clear from name
- ✅ **Clean Imports**: `from controller_hello_world import HelloWorldController`  
- ✅ **Scalable Organization**: No folder depth needed
- ✅ **IDE Support**: Grouped alphabetically by module type
- ✅ **Dependency Clarity**: Import patterns show architectural layers

---

## 📋 **CORE ARCHITECTURE PREFIXES**

### **`controller_`** - Orchestration Layer
**Purpose**: Job→Stage→Task orchestration, workflow management  
**Responsibility**: Coordinate stages, manage job lifecycle, result aggregation  
**Examples**:
- `controller_base.py` - Abstract base controller with common orchestration logic
- `controller_hello_world.py` - Hello World job orchestration implementation
- `controller_raster_processing.py` - Raster workflow orchestration (future)
- `controller_stac_catalog.py` - STAC cataloging workflow orchestration (future)

### **`repository_`** - Data Access Layer  
**Purpose**: Storage abstraction, data persistence, CRUD operations  
**Responsibility**: Database operations, storage backend abstraction  
**Examples**:
- `repository_data.py` - Jobs, tasks, and completion detection repositories
- `repository_stac.py` - STAC catalog data access (future)
- `repository_metrics.py` - Performance metrics and monitoring data (future)

### **`service_`** - Business Logic Layer
**Purpose**: Domain-specific business operations, processing logic  
**Responsibility**: Core business rules, data transformation, external integrations  
**Examples**:
- `service_hello_world.py` - Hello World task implementations and business logic
- `service_raster_processor.py` - Raster processing operations (future)
- `service_cog_converter.py` - COG conversion business logic (future)
- `service_metadata_extractor.py` - Metadata extraction logic (future)

---

## 🔧 **INFRASTRUCTURE PREFIXES**

### **`schema_`** - Data Schema Definitions
**Purpose**: Pydantic models, data validation, type definitions  
**Responsibility**: Strong typing discipline, schema enforcement  
**Examples**:
- `schema_core.py` - Core JobRecord, TaskRecord, and queue message schemas
- `schema_stac.py` - STAC-specific schema definitions (future)
- `schema_raster.py` - Raster processing data schemas (future)

### **`validator_`** - Validation Logic
**Purpose**: Schema validation, business rule validation, data integrity  
**Responsibility**: Fail-fast validation, error handling, data sanitization  
**Examples**:
- `validator_schema.py` - Core schema validation engine with Pydantic
- `validator_business.py` - Business rule validation logic (future)
- `validator_file.py` - File format and content validation (future)

### **`adapter_`** - External System Integration
**Purpose**: Storage backends, external APIs, third-party integrations  
**Responsibility**: Interface adaptation, protocol translation, connection management  
**Examples**:
- `adapter_storage.py` - Azure Table Storage, PostgreSQL, CosmosDB adapters
- `adapter_blob.py` - Azure Blob Storage operations (future)
- `adapter_queue.py` - Azure Service Bus, Redis queue adapters (future)
- `adapter_keyvault.py` - Azure Key Vault integration (future)

### **`model_`** - Data Models & Abstractions
**Purpose**: Data transfer objects, base classes, abstract models  
**Responsibility**: Data structure definitions, inheritance hierarchies  
**Examples**:
- `model_core.py` - Core data models and DTOs
- `model_job_base.py` - Abstract base job definition
- `model_stage_base.py` - Abstract base stage definition  
- `model_task_base.py` - Abstract base task definition

### **`config_`** - Configuration Management
**Purpose**: Settings, environment variables, configuration loading  
**Responsibility**: Application configuration, feature flags, environment setup  
**Examples**:
- `config_settings.py` - Core application configuration and settings
- `config_database.py` - Database connection configuration (future)
- `config_azure.py` - Azure-specific configuration (future)

### **`util_`** - Utility Functions
**Purpose**: Common helpers, shared utilities, infrastructure support  
**Responsibility**: Reusable functions, logging, monitoring, health checks  
**Examples**:
- `util_completion.py` - Completion orchestration utilities
- `util_logger.py` - Logging setup and configuration
- `util_retry.py` - Retry logic and error handling (future)
- `util_metrics.py` - Performance monitoring utilities (future)

---

## 🎯 **DOMAIN-SPECIFIC PREFIXES**

### **`stac_`** - STAC Catalog Operations
**Purpose**: STAC-specific functionality, catalog management, metadata operations  
**Examples**:
- `stac_check.py` - STAC item validation and checking
- `stac_catalog.py` - STAC catalog operations (future)
- `stac_metadata.py` - STAC metadata extraction (future)

### **`tiling_`** - Spatial Tiling Operations  
**Purpose**: PostGIS tiling, spatial processing, tile generation  
**Examples**:
- `tiling_plan.py` - Tiling plan generation and management
- `tiling_processor.py` - Tile processing logic (future)
- `tiling_optimizer.py` - Tiling performance optimization (future)

### **`raster_`** - Raster Processing Operations
**Purpose**: Raster data processing, format conversion, analysis  
**Examples** (Future):
- `raster_processor.py` - Core raster processing orchestration
- `raster_validator.py` - Raster format and content validation
- `raster_reprojector.py` - Coordinate system reprojection
- `raster_cog_converter.py` - Cloud Optimized GeoTIFF conversion

### **`database_`** - Database Operations
**Purpose**: Direct database operations, migrations, health checks  
**Examples** (Future):
- `database_health.py` - Database connectivity and health monitoring
- `database_migration.py` - Schema migration utilities
- `database_direct.py` - Direct SQL operations and queries

### **`queue_`** - Message Queue Processing
**Purpose**: Queue message handling, processing logic, queue management  
**Examples** (Future):
- `queue_processor.py` - Core queue message processing
- `queue_retry.py` - Queue retry and dead letter handling
- `queue_monitor.py` - Queue health and performance monitoring

---

## 🚫 **SPECIAL FILES (NO PREFIX)**

### **Entry Points & Infrastructure**
- `function_app.py` - Azure Functions entry point (unchanged)
- `__init__.py` - Package initialization
- `requirements.txt` - Dependencies
- `host.json` - Azure Functions configuration

### **Test Files**
- `test_*.py` - All test files use `test_` prefix (existing convention)
- Located in root directory (not organized by module prefix)

### **Documentation Files**
- `*.md` - Markdown documentation files
- No prefix needed, organized by content purpose

### **Configuration Files**
- `local.settings.json` - Local Azure Functions settings
- `*.json` - JSON configuration files
- `*.sh` - Shell scripts for deployment/automation

---

## 📐 **NAMING RULES & GUIDELINES**

### **Prefix Rules**
1. **Always lowercase** - `controller_` not `Controller_`
2. **Underscore separator** - `controller_hello_world.py` not `controller-hello-world.py`
3. **Descriptive names** - `controller_hello_world.py` not `controller_hw.py`
4. **Singular nouns** - `repository_data.py` not `repositories_data.py`

### **Descriptive Name Rules**
1. **Snake_case** - `hello_world` not `HelloWorld` or `helloWorld`
2. **Purpose-driven** - `validator_schema.py` (what it validates) not `validator_pydantic.py` (how it validates)
3. **Domain-specific** - `stac_catalog.py` not `catalog_stac.py`
4. **Avoid abbreviations** - `controller_hello_world.py` not `controller_hw.py`

### **Import Guidelines**
```python
# ✅ GOOD - Clear module identification
from controller_hello_world import HelloWorldController
from repository_data import JobRepository, TaskRepository
from schema_core import JobRecord, TaskRecord
from validator_schema import SchemaValidator

# ❌ BAD - Ambiguous module source
from hello_world import HelloWorldController  # What layer is this?
from data import JobRepository                 # Too generic
from core import JobRecord                     # Which core?
```

---

## 🎯 **FUTURE EXPANSION PREFIXES**

As the system grows, we anticipate these additional prefixes:

### **Additional Infrastructure**
- **`api_`** - API-specific handlers, middleware, routing
- **`auth_`** - Authentication, authorization, security components
- **`monitor_`** - Monitoring, health checks, metrics collection
- **`workflow_`** - Complex workflow orchestration beyond job→stage→task

### **Additional Domain Areas**
- **`vector_`** - Vector data processing operations
- **`metadata_`** - Metadata extraction and management
- **`spatial_`** - Spatial analysis and processing
- **`integration_`** - Third-party service integrations

### **Specialized Operations**
- **`batch_`** - Batch processing operations
- **`stream_`** - Streaming data operations  
- **`cache_`** - Caching operations and management
- **`security_`** - Security-specific operations

---

## 🔄 **MIGRATION STRATEGY**

### **From Old Names to New Names**
When renaming existing files:

1. **Identify Layer**: Determine if file is controller, repository, service, etc.
2. **Choose Prefix**: Select appropriate module prefix from conventions above
3. **Update Imports**: Find and replace all import statements using the file
4. **Update Tests**: Update test imports and references
5. **Update Documentation**: Update any documentation references

### **Import Statement Updates**
```python
# OLD (before prefixes)
from hello_world_controller import HelloWorldController
from repositories import JobRepository
from core_schema import JobRecord

# NEW (with prefixes)  
from controller_hello_world import HelloWorldController
from repository_data import JobRepository
from schema_core import JobRecord
```

---

## ✅ **CURRENT FILE ORGANIZATION**

### **Implemented (August 29, 2025)**
```
controller_base.py           # ✅ Base controller abstraction
controller_hello_world.py    # ✅ Hello World controller implementation

repository_data.py           # ✅ Data repositories (jobs, tasks, completion)

service_hello_world.py       # ✅ Hello World business logic services

schema_core.py              # ✅ Core Pydantic schema definitions  
validator_schema.py         # ✅ Schema validation engine

adapter_storage.py          # ✅ Storage backend adapters

model_core.py               # ✅ Core data models and DTOs
model_job_base.py           # ✅ Base job abstraction
model_stage_base.py         # ✅ Base stage abstraction  
model_task_base.py          # ✅ Base task abstraction

config_settings.py          # ✅ Configuration management

util_completion.py          # ✅ Completion orchestration utilities
util_logger.py              # ✅ Logging setup utilities

stac_check.py              # ✅ STAC-specific operations
tiling_plan.py             # ✅ Tiling-specific operations

function_app.py            # ✅ Azure Functions entry point (unchanged)
```

---

## 🎉 **BENEFITS ACHIEVED**

### **Developer Experience**
- ✅ **Instant File Purpose Recognition** - No need to open file to understand its role
- ✅ **IDE Organization** - Files grouped alphabetically by module type
- ✅ **Import Clarity** - Import statements clearly show architectural layers
- ✅ **Scalable Without Folders** - Clean organization without deep directory hierarchies

### **Architectural Benefits**
- ✅ **Clear Separation of Concerns** - Each prefix represents distinct architectural layer
- ✅ **Dependency Management** - Easy to identify cross-layer dependencies
- ✅ **Refactoring Support** - Easy to move functionality between modules
- ✅ **Testing Organization** - Clear mapping between implementation and test files

### **Maintenance Benefits**
- ✅ **Consistent Patterns** - Predictable file organization across entire codebase
- ✅ **New Developer Onboarding** - Naming convention makes architecture self-documenting
- ✅ **Code Review Efficiency** - Reviewers can quickly understand file purpose and dependencies
- ✅ **Documentation Alignment** - File names match architectural documentation

---

**UPDATE FREQUENCY**: Update this document when adding new module prefixes or architectural layers to maintain consistency across the codebase.