# Architecture File Index

**Azure Geospatial ETL Pipeline - File Catalog & Architecture Alignment**

*Updated: 2025-09-11 - Phase 5 Documentation Complete*

## 📁 File Overview

This document provides a comprehensive index of all files in the Azure Geospatial ETL Pipeline, organized by architectural layer. It serves as a companion to ARCHITECTURE_CORE.md, mapping implementation files to the architecture patterns described there.

**Total Python Files: 28**
- **Controllers**: 3 files (controller_base, controller_factories, controller_hello_world)
- **Interfaces**: 1 file (interface_repository - behavior contracts)
- **Repositories**: 5 files (repository_base, repository_factory, repository_jobs_tasks, repository_postgresql, repository_vault)
- **Services**: 3 files (service_factories, service_hello_world, schema_manager)
- **Schemas**: 5 files (schema_base, schema_queue, schema_sql_generator, schema_workflow, + queue separation)
- **Triggers**: 7 files (trigger_db_query, trigger_get_job_status, trigger_health, trigger_http_base, trigger_poison_monitor, trigger_schema_pydantic_deploy, trigger_submit_job)
- **Utilities**: 2 files (util_import_validator, util_logger)
- **Core/Config**: 2 files (function_app, config)

---

## 🚀 **Core Application Files**

### **function_app.py** ⭐ ENHANCED ✅ **[HEADER COMPLETE]**
- **Primary Azure Functions entry point**
- HTTP triggers for job submission (`/api/jobs/{job_type}`)
- Queue triggers for job and task processing (`geospatial-jobs`, `geospatial-tasks`)
- Timer triggers for poison queue monitoring
- Controller routing for Pydantic Job→Task architecture
- **Enhanced with strongly typed LoggerFactory for comprehensive debugging**
- **Status**: ✅ **FULLY OPERATIONAL** - Queue processing working, poison queue issues resolved! 🎊

### **host.json**
- **Azure Functions runtime configuration**
- Logging levels and Application Insights setup
- Queue processing settings (batch size: 16, max dequeue: 5)
- Function timeout configuration (5 minutes)
- Extension bundle configuration for Azure Functions v4

### **requirements.txt**
- **Python package dependencies**
- Azure SDK packages (functions, storage, identity, data-tables)
- Geospatial libraries (rasterio, rio-cogeo)
- **Pydantic v2+ for strong typing discipline**
- PostgreSQL driver (psycopg[binary])

---

### **📋 Core Architecture Prefixes**

#### **`controller_`** - Orchestration Layer
**Purpose**: Job→Stage→Task orchestration, workflow management
**Examples**: `controller_base.py`, `controller_hello_world.py`

#### **`interface_`** - Behavior Contracts (Pure ABCs) ⭐ NEW
**Purpose**: Abstract base classes defining behavior contracts without implementation
**Key Principle**: Pure interfaces with no data, only method signatures
**Examples**: `interface_repository.py` - Repository method contracts
**Benefits**: 
- Clear separation between contracts and implementations
- Prevents circular dependencies
- Enables dependency inversion principle

#### **`repository_`** - Data Access Layer (Concrete Implementations)
**Purpose**: Storage abstraction, data persistence, CRUD operations
**Implementation Pattern**: Implements interfaces from `interface_*.py` files
**Examples**: 
- `repository_postgresql.py` - Implements IJobRepository, ITaskRepository
- `repository_jobs_tasks.py` - Business logic repositories
- `repository_factory.py` - Factory for creating repository instances

#### **`service_`** - Business Logic Layer
**Purpose**: Domain-specific business operations, processing logic
**Examples**: `service_hello_world.py`, `service_factories.py`

#### **`schema_`** - Data Schema Definitions (Pure Data Models)
**Purpose**: Pydantic models, data validation, type definitions
**Key Principle**: Pure data structures with no behavior (except validation)
**Examples**: `schema_base.py`, `schema_workflow.py`, `schema_queue.py`


#### **`util_`** - Utility Functions
**Purpose**: Common helpers, shared utilities, infrastructure support
**Examples**: `util_logger.py`, `util_import_validator.py`

#### **`trigger_`** - HTTP/Timer Triggers ✅ **[ALL HEADERS COMPLETE]**
**Purpose**: Azure Functions HTTP and timer trigger implementations
**Examples**: All trigger files now have complete standardized headers:
- `trigger_http_base.py` - Base class for all HTTP triggers
- `trigger_submit_job.py` - Job submission endpoint
- `trigger_get_job_status.py` - Status retrieval endpoint  
- `trigger_health.py` - System health monitoring
- `trigger_db_query.py` - Database query endpoints (/api/db/*)
- `trigger_poison_monitor.py` - Poison queue monitoring
- `trigger_schema_pydantic_deploy.py` - Schema deployment

## ⚙️ **Configuration Files**

### **config.py** ✅ **[HEADER COMPLETE]**
- **Strongly typed configuration management with Pydantic v2**
- Centralized environment variable validation and documentation
- Azure storage, PostgreSQL, and queue configuration
- Single source of truth for all application settings
- Built-in validation with clear error messages


### **local.settings.json**
- **Local development configuration**
- Environment variables for Azure Functions local runtime
- Managed identity configuration for storage services
- **Contains sensitive data - not for production deployment**

### **local.settings.example.json**
- **Template for local development setup**
- Example configuration without sensitive values
- Reference for required environment variables

### **INFRA_CONFIG.md**
- **Azure infrastructure documentation**
- Function app configuration (rmhgeoapibeta)
- Storage account setup with managed identity
- Environment variables and RBAC permissions
- Local development setup instructions

---

## 🏗️ **Architecture & Factory Pattern**

### **controller_factories.py** ✅ **[HEADER COMPLETE]**
- **Factory pattern for controller instantiation**
- JobRegistry singleton for decorator-based registration
- Controller creation via `JobFactory.create_controller(job_type)`
- Workflow validation and job type management
- Prevents direct controller instantiation

---

## 🎛️ **Controllers (Job→Task Pattern)**

### **controller_base.py** ✅ **[HEADER COMPLETE]**
- **Abstract base controller for all job types**
- Workflow definition integration and parameter validation
- Job ID generation (SHA256 hash for idempotency)
- Stage orchestration and task creation patterns
- **Core architecture foundation for extensibility**

### **controller_hello_world.py** ✅ **[HEADER COMPLETE]**
- **Hello World controller implementation**
- Demonstrates complete Job→Task workflow
- Multi-task creation with parameter validation (n parameter)
- Result aggregation and completion detection
- **Status**: Fully implemented and tested

---

## 📋 **Schema & Validation**

### **schema_core.py** ✅ **[HEADER COMPLETE]**
- **Core schema definitions for strong typing**
- Parameter validation schemas
- Error handling and validation patterns
- Type safety enforcement classes

### **schema_workflow.py** ✅ **[HEADER COMPLETE]**
- **Workflow definition schemas**
- Stage-based workflow validation
- Operation type definitions and routing
- Parameter schema validation per workflow stage


### **schema_base.py** ✅ **[HEADER COMPLETE]**
- **Unified Pydantic + ABC base classes**
- Single source of truth for data and behavior
- BaseTask, BaseJob, BaseStage definitions
- Execution context models

### **schema_queue.py** ✅ **[HEADER COMPLETE]**
**Layer**: Schema/Data Models  
**Purpose**: Queue-specific message schemas for Azure Queue Storage  
**Key Components**:
- `JobQueueMessage`: Job queue message format
- `TaskQueueMessage`: Task queue message format
- Queue message validation utilities

**Relationships**:
- Separated from `schema_base.py` for better modularity
- Used by `function_app.py`, `controller_base.py`, `service_factories.py`
- Enables queue message evolution independent of database schemas

### **schema_sql_generator.py** ✅ **[HEADER COMPLETE]**
- **PostgreSQL DDL generation from Pydantic models**
- Automatic schema generation
- Type mapping from Python to PostgreSQL
- Single source of truth for database schema

---

## 🔧 **Services & Processing**

### **service_factories.py** ⭐ **NEW** ✅ **[HEADER COMPLETE]**
- **Task handler registry and factory implementation**
- Implements Robert's implicit lineage pattern for multi-stage workflows
- TaskRegistry singleton for handler registration via decorators
- TaskHandlerFactory creates handlers with predecessor data access
- TaskContext provides automatic lineage tracking (a1b2c3d4-s2-tile_x5_y10 → a1b2c3d4-s1-tile_x5_y10)
- **Status**: Replaces hardcoded task routing in function_app.py

### **service_hello_world.py** ✅ **[HEADER COMPLETE]**
- **Hello World service implementation**
- Demonstrates service layer patterns
- Task processing and result generation
- Now registers handlers via @TaskRegistry decorators
- **Status**: Implementation for Job→Task architecture

### **schema_manager.py** ✅ **[HEADER COMPLETE]**
- **PostgreSQL schema management infrastructure**
- Database initialization and validation
- Schema creation and table management
- Permission verification
- NOTE: Part of schema infrastructure, not a business service


### **repository_base.py** ✅ **[HEADER COMPLETE]**
- **Pure abstract base repository class**
- Common validation and error handling patterns
- No storage dependencies
- Template method pattern implementation

### **repository_postgresql.py** ✅ **[HEADER COMPLETE]**
- **PostgreSQL-specific repository implementation**
- Direct database access with psycopg
- Atomic operations for race condition prevention
- Connection pooling and transaction support

### **repository_jobs_tasks.py** ✅ **[HEADER COMPLETE]**
- **Business logic repository for job and task management**
- Inherits from PostgreSQL base classes
- JobRepository, TaskRepository, CompletionDetector implementations
- Renamed from repository_consolidated.py for clarity

### **repository_factory.py** ⭐ **NEW** ✅ **[HEADER COMPLETE]**
- **Central factory for creating all repository instances**
- Extracted from repository_consolidated.py for clean separation
- Single point for repository instantiation
- Future support for blob, cosmos, redis repositories

### **interface_repository.py** ✅ **[HEADER COMPLETE]** ⭐ RENAMED
- **Pure behavior contracts for all repository operations**
- Renamed from `repository_abc.py` for clarity (11 Sept 2025)
- Abstract base classes with no implementation
- Defines IJobRepository, ITaskRepository, ICompletionDetector
- Single source of truth for method signatures
- Prevents circular dependencies through clean separation

### **repository_vault.py** ✅ **[HEADER COMPLETE]**
- **Azure Key Vault credential management**
- Currently disabled pending RBAC setup
- Secure password retrieval patterns
- Caching with TTL support

---

## 🛠️ **Utilities**


### **util_logger.py** ⭐ ENHANCED ✅ **[HEADER COMPLETE]**
- **Strongly typed logger factory implementation**
- Component-specific loggers (Queue, Controller, Service, Repository)
- Correlation ID tracing for end-to-end request tracking
- Azure Application Insights integration with custom dimensions
- Visual error indicators with emojis for rapid log parsing
- **Status**: ✅ **DEPLOYED** - Enhanced debugging infrastructure operational


### **util_import_validator.py** ✅ **[HEADER COMPLETE]**
- **Zero-configuration import validation system**
- Auto-discovery of application modules
- Two-tier validation (critical deps + app modules)
- Persistent registry tracking with health checks



---

## 📚 **Documentation**

### **ARCHITECTURE_CORE.md** ⭐ **PRIMARY REFERENCE**
- **Detailed technical architecture specification**
- Job→Stage→Task pattern implementation details
- Queue message schemas and state transitions
- PostgreSQL atomic operations and functions
- TaskFactory for high-volume task creation

### **CLAUDE.md**
- **Primary project context and instructions for Claude AI**
- Quick navigation index for easy reference
- Current priorities and operational status
- Development philosophy (No Backward Compatibility)

### **ARCHITECTURE_FILE_INDEX.md**
- **This document - comprehensive file catalog**
- Maps files to architecture patterns in ARCHITECTURE_CORE.md
- Organized by architectural layer
- File naming conventions and standards

### **TODO.md** 🎯 **ACTIVE**
- **Current development priorities**
- Error handling implementation phases
- Stage advancement logic tasks
- Future enhancements roadmap

### **HISTORY.md** 📜
- **Completed architectural changes**
- Repository cleanup achievements (7 September 2025)
- Factory pattern implementation (7 September 2025)
- Database monitoring system (3 September 2025)

### **claude_log_access.md** 🔑 **DEPLOYMENT CRITICAL**
- **Application Insights log access instructions**
- Bearer token authentication setup
- Log streaming configuration
- Debugging guidance for Azure Functions

### **POSTGRESQL_WORKFLOW_IMPLEMENTATION.md**
- **PostgreSQL workflow function details**
- Atomic operation specifications
- Stage advancement logic
- Job completion detection patterns

### **CONFIGURATION_USAGE.md**
- **Comprehensive configuration usage guide**
- Strongly typed configuration examples with Pydantic v2
- Environment variable documentation and validation
- Migration guide from scattered configuration approach


### **INFRA_CONFIG.md**
- **Azure infrastructure documentation**
- Function app configuration (rmhgeoapibeta)
- Storage account setup with managed identity
- Environment variables and RBAC permissions

### **HELLO_WORLD_IMPLEMENTATION_PLAN.md**
- **Implementation documentation for hello_world controller**
- Step-by-step implementation details
- Testing and validation procedures
- Architecture demonstration patterns

### **POISON_QUEUE_DEBUGGING_REPORT.md** 📚 **HISTORICAL**
- **Complete poison queue investigation report (Sep 1, 2025)**
- Four major technical issues identified and resolved
- Root cause analysis with systematic investigation
- **Status**: ✅ **RESOLVED** - Issues fixed, see HISTORY.md

### **STRONG_TYPING_ARCHITECTURE_STATUS.md** 📚 **HISTORICAL**
- **Strong typing implementation status**
- Pydantic v2 integration documentation
- Type safety enforcement patterns
- **Status**: ✅ **COMPLETED** - Strong typing fully implemented

### **consolidated_redesign.md** 📚 **HISTORICAL**
- **Architecture redesign documentation**
- Job→Stage→Task pattern specifications
- Controller orchestration patterns
- **Historical reference for architecture evolution**

---

## 🔨 **Utility Scripts**

### **FIX_APP_SETTINGS.sh**
- **Shell script for Azure Function App configuration**
- Environment variable deployment automation
- Configuration synchronization utilities
- **Production deployment helper**

### **fix_sql_functions.py**
- **PostgreSQL function repair utility**
- Fixes function signature mismatches
- Updates SQL functions to match Python interfaces
- Development-only debugging tool

---

## 📦 **Archive Files**

### **Archive.zip**
- **Archived previous implementations**
- Historical code versions

---

## 🎯 **Current Architecture Status (September 2025)**

### **✅ Completed Architecture Components**
- **Job→Stage→Task Pattern**: Fully implemented with atomic PostgreSQL operations
- **Factory Pattern**: JobFactory and decorator-based controller registration
- **Repository Pattern**: Clean hierarchy from interfaces to business logic
- **Queue Processing**: Both job and task queues operational
- **Database Integration**: PostgreSQL with atomic completion detection
- **Strong Typing**: Pydantic v2 throughout with schema-driven validation

### **🔴 Current Priority**
- See TODO.md for current development priorities and tasks

### **webapp_logs.zip**
- **Archived application logs**
- Historical debugging information
- **Reference for troubleshooting patterns**

---

## 🏷️ **System Files**

### **__init__.py**
- **Python package initialization**
- Module export definitions
- Package-level configuration

---

## 📊 **File Organization Summary**

### **By Architectural Layer**

#### Schema Layer - Foundation of Application Architecture
The `schema_*` files define the **core structure** of the entire application:
- **Definition**: Data models, workflow patterns, and architectural contracts
- **Implementation**: SQL generation and database schema deployment
- **Validation**: Type safety, constraints, and structural integrity across all layers

**Schema Files:**
- `schema_base.py` - Core data models (JobRecord, TaskRecord), enums, and base controller with completion logic
- `schema_workflow.py` - Workflow definitions, stage patterns, and orchestration contracts
- `schema_sql_generator.py` - Converts Pydantic models to PostgreSQL DDL (single source of truth)
- `schema_manager.py` - Deploys and validates database schemas, ensures structural integrity

#### Repository Layer - State Management for Serverless Architecture
The `repository_*` files are **critical for serverless state management** - Python handles logic, PostgreSQL manages state:
- **State Management**: All application state lives in PostgreSQL (serverless functions are stateless)
- **ACID Guarantees**: PostgreSQL functions ensure atomicity, preventing race conditions
- **Atomic Operations**: "Last task turns out the lights" pattern via PostgreSQL stored procedures
- **Transaction Safety**: Critical operations like `complete_task_and_check_stage()` are atomic

**Serverless Architecture Principle:**
```
Stateless Python Functions → Repository Layer → Stateful PostgreSQL
     (Business Logic)        (State Interface)    (ACID State Management)
```

**Repository Architecture (Interface/Implementation Pattern):**
- `interface_repository.py` - Pure abstract interfaces (IJobRepository, ITaskRepository)
- `repository_base.py` - Common validation and error handling patterns  
- `repository_postgresql.py` - PostgreSQL implementation with atomic stored procedures
- `repository_jobs_tasks.py` - High-level repositories implementing interfaces
- `repository_factory.py` - Factory pattern for repository instantiation

**Interface/Implementation Separation Benefits:**
1. **Clean Contracts**: Interfaces define "what" without "how"
2. **No Circular Dependencies**: Interfaces have no imports from implementations
3. **Testability**: Easy to mock interfaces for testing
4. **Flexibility**: Multiple implementations can satisfy same interface
5. **Dependency Inversion**: Upper layers depend on interfaces, not concrete classes

#### Controller-Service-Repository Pattern Flow
```
HTTP Request → Trigger → Controller → Service → Repository → Storage
                            ↓            ↓           ↓           ↓
                      Orchestration  Business   Data Access  Database/
                       & Workflow      Logic     Abstraction   Blob
```

**Responsibilities in Serverless Context:**
- **Controllers**: Orchestrate workflow, coordinate stages (stateless coordination)
- **Services**: Execute business logic, process data (stateless computation)
- **Repositories**: **Manage ALL state**, ensure ACID compliance, prevent race conditions

**Why Repository Layer Owns State Management:**
- Serverless functions have no persistent memory between invocations
- PostgreSQL provides ACID guarantees that prevent distributed system race conditions
- Stored procedures ensure atomic state transitions (e.g., task completion → stage advancement)
- Repository pattern abstracts this complexity from business logic
- This is NOT asking too much - it's the **correct serverless pattern**

## 🏛️ **Interface/Implementation Separation Pattern**

### **Architectural Principle: Separation of Contracts from Implementation**

The codebase follows a strict separation between behavior contracts (interfaces) and their implementations:

```
┌─────────────────────────────────────────────────────┐
│              BEHAVIOR CONTRACTS                      │
│         interface_*.py (Pure ABCs)                   │
│     No implementation, no dependencies               │
└──────────────────┬──────────────────────────────────┘
                   ↓ implements
┌─────────────────────────────────────────────────────┐
│           CONCRETE IMPLEMENTATIONS                   │
│    repository_*.py, service_*.py, controller_*.py   │
│         Implements interfaces, adds behavior         │
└─────────────────────────────────────────────────────┘
```

### **Pattern Application:**

1. **Interfaces (`interface_*.py`)**:
   - Pure abstract base classes
   - Only method signatures, no implementation
   - No dependencies on concrete classes
   - Example: `IJobRepository`, `ITaskRepository` in `interface_repository.py`

2. **Implementations (`repository_*.py`, etc.)**:
   - Concrete classes implementing interfaces
   - Contains actual business logic
   - Can have dependencies on other layers
   - Example: `JobRepository` implements `IJobRepository`

3. **Benefits Achieved:**
   - **Testability**: Mock interfaces easily for unit testing
   - **Flexibility**: Swap implementations without changing contracts
   - **Clear Architecture**: Obvious separation of concerns
   - **No Circular Dependencies**: Interfaces don't import implementations

### **Example Usage:**
```python
# interface_repository.py
class IJobRepository(ABC):
    @abstractmethod
    def create_job(self, job_record: JobRecord) -> JobRecord:
        pass

# repository_jobs_tasks.py  
class JobRepository(PostgreSQLJobRepository, IJobRepository):
    def create_job(self, job_record: JobRecord) -> JobRecord:
        # Actual implementation
        return self._execute_insert(...)

# controller_base.py
def __init__(self, job_repo: IJobRepository):  # Depends on interface
    self.job_repo = job_repo
```

---

| Layer | Prefix | Purpose | Key Files |
|-------|--------|-----------|-----------|
| **Interfaces** | `interface_` | Pure behavior contracts (ABCs) | interface_repository |
| **Schemas** | `schema_` | Pure data models (Pydantic) | schema_base, schema_workflow, schema_queue |
| **Controllers** | `controller_` | Job orchestration & workflow | controller_base, controller_hello_world |
| **Repositories** | `repository_` | Data access implementations | repository_postgresql, repository_jobs_tasks |
| **Services** | `service_` | Business logic & operations | service_hello_world, service_factories |
| **Triggers** | `trigger_` | HTTP/Timer entry points | trigger_submit_job, trigger_health |
| **Utilities** | `util_` | Cross-cutting concerns | util_logger, util_import_validator |

### **Claude Context Headers**

All production Python files include standardized headers with:
- **PURPOSE**: Single-sentence description
- **EXPORTS**: Classes and functions exposed
- **INTERFACES**: ABC implementations
- **DEPENDENCIES**: External and internal imports
- **PATTERNS**: Design patterns used
- **INDEX**: Line numbers for navigation

## 🎯 **Key Architecture Patterns**

1. **Pydantic Job→Task Architecture**: Strong typing with workflow definitions
2. **Controller Pattern**: Orchestration layer with parameter validation  
3. **Managed Identity**: Azure authentication without connection strings
4. **Queue-Based Processing**: Asynchronous job and task execution
5. **Distributed Completion**: "Last task turns out the lights" pattern

---

## 🚨 **Development Notes**

- **No Backward Compatibility**: Explicit error handling over fallbacks
- **Strong Typing Discipline**: Pydantic v2 enforcement throughout
- **Production Function App**: rmhgeoapibeta (ONLY active deployment)
- **Resource Group**: rmhazure_rg
- **Storage Account**: rmhazuregeo with managed identity

---

---

## 📂 **File Naming Convention Standards**

*Integrated from FILE_NAMING_CONVENTION.md*

### **🎯 Naming Philosophy**

**Prefix Pattern**: `{module_prefix}_{descriptive_name}.py`

**Benefits**:
- ✅ **Instant Recognition**: File purpose clear from name
- ✅ **Clean Imports**: `from controller_hello_world import HelloWorldController`
- ✅ **Scalable Organization**: No folder depth needed  
- ✅ **IDE Support**: Grouped alphabetically by module type
- ✅ **Dependency Clarity**: Import patterns show architectural layers

### **📐 Naming Rules & Guidelines**

#### **Prefix Rules**
1. **Always lowercase** - `controller_` not `Controller_`
2. **Underscore separator** - `controller_hello_world.py` not `controller-hello-world.py`
3. **Descriptive names** - `controller_hello_world.py` not `controller_hw.py`
4. **Singular nouns** - `repository_data.py` not `repositories_data.py`

#### **Import Guidelines**
```python
# ✅ GOOD - Clear module identification
from controller_hello_world import HelloWorldController
from repository_consolidated import JobRepository, TaskRepository
from schema_base import JobRecord, TaskRecord

# ❌ BAD - Ambiguous module source
from hello_world import HelloWorldController  # What layer is this?
from data import JobRepository                 # Too generic
from core import JobRecord                     # Which core?
```

### **🚫 Special Files (No Prefix)**

#### **Entry Points & Infrastructure**
- `function_app.py` - Azure Functions entry point (unchanged)
- `__init__.py` - Package initialization
- `config.py` - Configuration management (special case - widely understood)

#### **Test & Documentation Files**
- `test_*.py` - All test files use `test_` prefix
- `*.md` - Markdown documentation files
- `*.json` - JSON configuration files

---

## 📝 **Complete Python File Inventory**

### Alphabetical List (28 files)
```
config.py                         # Core configuration management
controller_base.py                # Abstract base controller
controller_factories.py           # JobFactory and TaskFactory
controller_hello_world.py         # Example controller implementation
function_app.py                   # Azure Functions entry point
interface_repository.py           # Repository behavior contracts (renamed from repository_abc.py)
repository_base.py                # Base repository patterns
repository_factory.py             # Central repository factory
repository_jobs_tasks.py         # Job and task repositories
repository_postgresql.py          # PostgreSQL implementation
repository_vault.py               # Key Vault integration (disabled)
schema_base.py                    # Core Pydantic models
schema_manager.py                 # Schema deployment infrastructure
schema_queue.py                   # Queue message schemas (separated from DB schemas)
schema_sql_generator.py           # Pydantic to SQL converter
schema_workflow.py                # Workflow definitions
service_hello_world.py            # Example service implementation
trigger_db_query.py               # Database query endpoints
trigger_get_job_status.py         # Job status endpoint
trigger_health.py                 # Health check endpoint
trigger_http_base.py              # Base HTTP trigger class
trigger_poison_monitor.py         # Poison queue endpoint
trigger_schema_pydantic_deploy.py # Schema deployment endpoint
trigger_submit_job.py             # Job submission endpoint
util_import_validator.py          # Import validation system
util_logger.py                    # Enhanced logging factory
```

---

*This index reflects the current state of the Azure Geospatial ETL Pipeline as of September 10, 2025. For architecture details, see ARCHITECTURE_CORE.md. For current priorities, see TODO.md and CLAUDE.md.*