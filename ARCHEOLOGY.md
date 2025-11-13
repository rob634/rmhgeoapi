# 🏛️ Documentation Archeology - Project Knowledge Map

**Date**: 11 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Concise summaries of all documentation for rapid understanding
**Total Files**: 107 markdown files across docs/ folder

---

## 📖 How to Use This Document

This is your **Rosetta Stone** for understanding the project's history and architecture without reading 100+ documents.

Each entry has:
- **File path** - Where to find the full document
- **30-line summary** - Key concepts, decisions, and outcomes
- **Category tags** - Quick filtering (ACTIVE, COMPLETED, HISTORICAL, REFERENCE)

**Reading Strategy**:
1. Start with **ACTIVE** docs (current system)
2. Read **REFERENCE** docs for technical details
3. Explore **COMPLETED** and **HISTORICAL** to understand evolution

---

## 📅 Project Timeline & Architectural Evolution

**Development Period**: ~3 months (September - November 2025)
**Current Status**: Production-ready, standards-compliant geospatial API platform

### Epoch-Based Architecture Evolution

**EPOCH 1-2**: Early Experimentation (Pre-September 2025)
- Initial Azure Functions + Queue Storage patterns
- Early job orchestration concepts
- Foundation for Job → Stage → Task pattern

**EPOCH 3**: BaseController Era (Early September 2025)
- ✅ Working multi-stage job orchestration
- ✅ PostgreSQL state management with advisory locks
- ✅ Queue Storage + Service Bus pipelines
- ⚠️ **Problem**: 2,290-line "God Class" (BaseController)
- ⚠️ **Problem**: Inheritance-based pattern, tight coupling
- **Lessons Learned**: Need composition over inheritance, declarative job definitions

**EPOCH 4**: CoreMachine Transition (29 SEP - 30 SEP 2025) ⭐ CURRENT
- 🎯 **Complete Restart**: Composition pattern replaces inheritance
- 🎯 **CoreMachine**: Universal orchestrator (490 lines, -78.6% reduction)
- 🎯 **Declarative Jobs**: ~50 lines per job (vs 1,000+ lines in Epoch 3)
- 🎯 **Data-Behavior Separation**: Base contracts (TaskData, JobData) with composition
- **Deployment Ready**: 30 SEP 2025 (all tests passing)

### Major Milestones

**September 2025** - Foundation
- 29 SEP: CoreMachine architecture vision published
- 30 SEP: Epoch 4 deployment ready, complete architecture transition
- Database connection strategy finalized (single-use connections for async ETL)

**October 2025** - Infrastructure Maturation
- 1 OCT: Data-behavior separation refactoring complete
- 3 OCT: Database connection strategy approved
- 4 OCT: Multi-phase cleanup campaign begins
- 14 OCT: H3 aggregation architecture designed
- 18 OCT: OGC Features API (vector_api.md) design complete
- 24 OCT: System status snapshot (stable)
- 25 OCT: **ALL MAJOR MIGRATIONS COMPLETE**
  - Storage Queues → Service Bus
  - Core schema migration to PostgreSQL
  - Function app cleanup and consolidation
  - Health endpoint cleanup
- 29 OCT: Platform layer operational, code quality reviews, STAC analysis
- 30 OCT: **OGC Features API operational** (browser tested, user celebration!)

**November 2025** - Production Polish
- 10 NOV: Unified API documentation (OGC + STAC)
- 10 NOV: Managed identity configuration for corporate environment
- 11 NOV: Documentation archeology and cleanup (this document!)

### Architecture Achievements

**Code Reduction**:
- Epoch 3 BaseController: 2,290 lines, 34 methods
- Epoch 4 CoreMachine: 490 lines, 12 methods
- **Result**: -78.6% lines, -64.7% methods

**Standards Compliance**:
- ✅ STAC v1.0.0 (metadata catalog)
- ✅ OGC API - Features Core 1.0 (vector data)
- ✅ GeoJSON-native output
- ✅ Production-ready Azure Functions

**Technology Stack Evolution**:
- **Storage**: Azure Storage Queues → Azure Service Bus (Oct 2025)
- **Database**: Azure Storage Tables → PostgreSQL 17 + PostGIS 3.6 + pgSTAC 0.8.5
- **Pattern**: Inheritance (BaseController) → Composition (CoreMachine)
- **Jobs**: Imperative 1,000-line controllers → Declarative 50-line definitions

### Key Design Decisions

1. **Single-Use Database Connections** (3 OCT 2025): Correct for async ETL workload
2. **Composition Over Inheritance** (29 SEP 2025): Eliminates God Class anti-pattern
3. **OGC Features for Vectors** (18 OCT 2025): STAC only for metadata, OGC for queries
4. **No Backward Compatibility** (Philosophy): Explicit errors force proper migration
5. **H3 Spatial Indexing** (14 OCT 2025): DuckDB + GeoParquet, skip PostGIS for aggregation

### Development Velocity

**Fast Iteration Period**: 29 SEP - 30 SEP 2025 (Epoch 4 transition in 2 days!)
**Migration Sprint**: 25 OCT 2025 (all major migrations completed same day)
**Standards Implementation**: 18 OCT - 30 OCT 2025 (OGC Features design → operational in 12 days)

**Total Development Time**: ~3 months for production-ready geospatial platform

---

## 🎯 Quick Navigation

### Essential Reading (Start Here)
- [docs/ARCHITECTURE_QUICKSTART.md](#docsarchitecture_quickstartmd) - 30-second system overview
- [docs/API_DOCUMENTATION.md](#docsapi_documentationmd) - OGC + STAC API reference
- [docs_claude/CLAUDE_CONTEXT.md](#docs_claudeclaude_contextmd) - Primary Claude context

### Active Documentation
- [docs/](#docs-root-5-files) - New user essentials
- [docs/reference/](#docsreference-3-files) - H3, DuckDB, Vector API guides
- [docs/architecture/](#docsarchitecture-7-files) - Core architecture docs

### Historical Archives
- [docs/completed/](#docscompleted-50-files) - Completed features, migrations, reviews
- [docs/archive/](#docsarchive-52-files) - Historical analysis, cleanup reports

---

## 📂 docs/ Root (5 files - New User Essentials)

### docs/API_DOCUMENTATION.md
**Status**: ✅ ACTIVE - Production documentation
**Date**: 10 NOV 2025
**Category**: USER_GUIDE

**Summary**:
Unified API documentation for OGC Features + STAC APIs. Two standards-compliant APIs for geospatial data access:

**OGC API - Features** (Vector Data):
- Query vector features (points, lines, polygons) from PostGIS
- Spatial filtering (bbox), temporal queries, attribute filtering
- Pagination, geometry simplification
- Example: GET /api/features/collections/{id}/items?bbox=-122.5,37.7,-122.3,37.9

**STAC API** (Metadata Catalog):
- STAC v1.0.0 compliant metadata discovery
- pgSTAC backend for collections and items
- Spatial/temporal extents
- Example: GET /api/stac/collections

**Key Features**:
- Standards-compliant (OGC, STAC specifications)
- Production-ready (Azure Functions serverless)
- Portable modules (can be deployed separately for APIM)
- GeoJSON-native (direct web map integration)

**Audience**: External users, API consumers, developers
**References**: ogc_features/README.md (2,600+ lines), stac_api/README.md

---

### docs/ARCHITECTURE_QUICKSTART.md
**Status**: ✅ ACTIVE - Onboarding document
**Date**: 5 OCT 2025
**Category**: ONBOARDING

**Summary**:
Rapid orientation for new Claude sessions and developers. 30-second summary + architecture diagrams.

**What**: Azure Functions-based geospatial processing orchestration system
**Pattern**: Job → Stage → Task with queue-driven parallelization
**Stack**: Python 3.12, PostgreSQL 17, PostGIS 3.6, PgSTAC 0.8.5, Azure Functions
**Philosophy**: No backward compatibility, explicit errors, single source of truth

**Essential Reading Order**:
1. docs_claude/CLAUDE_CONTEXT.md (Primary context)
2. docs_claude/TODO.md (Active tasks)
3. docs/TASK_REGISTRY_PATTERN.md (Job injection architecture)
4. POSTGRES_REQUIREMENTS.md (PostgreSQL setup)
5. docs_claude/FILE_CATALOG.md (Quick file lookup)

**Core Architecture**:
- Request Flow: HTTP → Trigger → Job Registry → Core Machine → Queue → Task Processors
- Job Pattern: Job contains Stages (sequential) → Stage contains Tasks (parallel)
- "Last Task Turns Out the Lights" - Atomic completion detection

**Quick Reference**: Points to all key files, deployment commands, testing procedures
**Audience**: New developers, AI agents, onboarding
**Time to Read**: 5-10 minutes for full orientation

---

### docs/postgres_managed_identity.md
**Status**: ✅ ACTIVE - Deployment configuration
**Date**: 10 NOV 2025
**Category**: DEPLOYMENT

**Summary**:
SQL commands for managed identity database access in World Bank corporate environment. Eliminates passwords and key vault complexity.

**ETL Identity** (rmh-etl-identity):
- CREATE privileges on app, geo, pgstac, h3 schemas
- Full DML permissions (SELECT, INSERT, UPDATE, DELETE)
- Can create tables, indexes, views, functions
- For dynamic PostGIS table creation as data arrives

**TiTiler Identity** (read-only):
- SELECT-only permissions on pgstac, geo schemas
- No CREATE privilege (prevents accidental table creation)
- Perfect separation of concerns

**SQL Grants Pattern**:
```sql
GRANT USAGE, CREATE ON SCHEMA geo TO "rmh-etl-identity";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA geo TO "rmh-etl-identity";
ALTER DEFAULT PRIVILEGES IN SCHEMA geo GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "rmh-etl-identity";
```

**Purpose**: Production deployment configuration for corporate Azure migration
**Audience**: DevOps, database administrators
**Use Case**: WB corporate environment with managed identities

---

### docs/DOCS_FOLDER_ANALYSIS.md
**Status**: 📋 META - Documentation cleanup analysis
**Date**: 11 NOV 2025
**Category**: CLEANUP

**Summary**:
Analysis of docs/ folder cleanup - identified 14 files to archive (11 architecture, 3 STAC strategy).

**Files to Keep** (3 essential):
1. ARCHITECTURE_QUICKSTART.md - Onboarding
2. API_DOCUMENTATION.md - API reference
3. postgres_managed_identity.md - Deployment config

**Files Archived** (14 historical):
- Architecture transition docs (Epoch 4 implementation complete)
- STAC strategy decisions (OGC Features chosen for vectors)
- Analysis documents (markdown cleanup from 11 NOV)

**Result**: Clean docs/ folder with only new user essentials
**Total Archived**: 50 files (30 from earlier + 20 from migrations/epoch)
**Purpose**: Better organization, improved new user experience

---

### docs/MIGRATIONS_EPOCH_ANALYSIS.md
**Status**: 📋 META - Migration/epoch folder analysis
**Date**: 11 NOV 2025
**Category**: CLEANUP

**Summary**:
Analysis of docs/migrations/ and docs/epoch/ folders - both archived to docs/completed/.

**migrations/** (6 files, all 25 OCT 2025):
- Storage Queue → Service Bus migration (COMPLETE)
- Core schema migration (COMPLETE)
- Function app cleanup (COMPLETE)
- Health endpoint cleanup (COMPLETE)
- All completion reports, no active work

**epoch/** (14 files, Sept-Oct 2025):
- Epoch 3→4 transition documentation
- Deployment readiness (30 SEP 2025 - PASSED)
- Phase 1-4 summaries (ALL COMPLETE)
- Epoch 4 is CURRENT system (live since Sept-Oct 2025)
- 32KB EPOCH3.md (historical reference)
- 32KB epoch4_framework.md (framework complete)

**Recommendation**: Archive both folders (all work complete)
**Result**: 20 additional files archived, cleaner docs/ structure

---

### docs/REFERENCE_FOLDER_ANALYSIS.md
**Status**: 📋 META - Reference folder analysis
**Date**: 11 NOV 2025
**Category**: CLEANUP

**Summary**:
Analysis of docs/reference/ folder - recommended keeping 2 active files, archiving 1 completed.

**KEEP** (2 files - Active/Future):
1. H3.md (29KB) - H3 aggregation architecture
   - Jobs exist: create_h3_base.py, generate_h3_level4.py
   - DuckDB integration planned but not implemented
   - 5-phase roadmap for future work

2. duckdb_parameter.md (18KB) - DuckDB parameterization guide
   - Security-critical (SQL injection prevention)
   - Future implementation reference
   - Complements H3.md architecture

**ARCHIVE** (1 file - Implementation Complete):
3. vector_api.md (17KB) - OGC Features MVP design
   - Implementation 100% complete (ogc_features/ module operational)
   - Better docs exist: ogc_features/README.md (2,600+ lines), API_DOCUMENTATION.md
   - Design doc served its purpose, now historical

**Decision**: Keep active/future references, archive completed implementations
**Result**: Cleaner reference folder with only relevant docs

---

## 📂 docs/reference/ (3 files - Technical References)

### docs/reference/H3.md
**Status**: 🔶 ACTIVE - Partial implementation
**Date**: 14 OCT 2025
**Category**: REFERENCE, DESIGN

**Summary**:
H3 aggregation architecture for massively parallelized global-scale geospatial visualization using Azure Functions, DuckDB, and Overture Maps data.

**Goal**: Aggregate geospatial data into H3 grid cells at levels 6-7 for global sphere visualization
**Immediate Focus**: Proof of concept at level 6 for Panama and Liberia using Overture GeoParquet
**Future Scope**: Zonal statistics on raster data from Planetary Computer

**Core Architecture Decisions**:
1. **Skip PostGIS** - Use direct GeoParquet processing (Overture → DuckDB → Aggregated GeoParquet)
2. **H3 IS the Batching Strategy** - Natural geographic batching (Level 3 parents → 3,000 children each)
3. **Queue-Based Orchestration** - HTTP Trigger → Create Batches → Queue Messages → Parallel Processing

**Implementation Status**:
- ✅ Jobs exist: create_h3_base.py, generate_h3_level4.py
- ⚠️ Services incomplete (no H3 services yet)
- ⚠️ DuckDB: Config exists but no implementation

**5-Phase Roadmap**:
- Phase 1: Point aggregation (places, addresses, buildings)
- Phase 2: Raster zonal stats (population density, land cover)
- Phase 3: Temporal analysis (change detection, growth trajectories)
- Phase 4: Multi-resolution hierarchies (dynamic zoom)
- Phase 5: Cross-theme analysis (roads within 100m of buildings)

**Cost Analysis**: ~$35 per complete global run
**Performance**: 10-minute timeout design, batch sizes for Azure Functions limits
**Testing Strategy**: Single H3 cell → Panama → Liberia region validation

**Why KEEP**: Active development area, valuable roadmap, no better H3 documentation exists

---

### docs/reference/duckdb_parameter.md
**Status**: ⚠️ REFERENCE - Not yet implemented
**Date**: 14 OCT 2025
**Category**: REFERENCE, SECURITY

**Summary**:
DuckDB parameterization patterns and SQL injection prevention guide. Technical reference for safe query composition.

**Purpose**: Build safe query patterns similar to psycopg's `sql.SQL()` composition for DuckDB

**DuckDB Parameterization Methods**:
1. Positional parameters (`?`): `conn.execute("SELECT * FROM table WHERE id = ?", [123])`
2. Named parameters (`$name`): `conn.execute("SELECT * WHERE id = $id", {'id': 123})`

**Key Difference from psycopg3**:
- psycopg has `sql.SQL()` composition for safe query building
- DuckDB doesn't have built-in composition library
- Need custom safe abstraction

**What CAN Be Parameterized** (use `?` or `$name`):
- Values in WHERE clauses
- Values in INSERT/UPDATE
- Literal values, numeric parameters

**What CANNOT Be Parameterized** (need safe composition):
- Table names, column names
- File paths (e.g., in `read_parquet()`)
- Function names, SQL keywords

**Recommended Approach**: Safe Query Builder pattern
- Validate identifiers against whitelist
- Quote identifiers properly
- Prevent SQL injection

**Why KEEP**: Essential for future DuckDB implementation, security-critical guidance, complements H3.md

---

### docs/reference/vector_api.md
**Status**: ✅ COMPLETED - Implementation superseded
**Date**: 18 OCT 2025
**Category**: HISTORICAL, DESIGN

**Summary**:
OGC API-Features MVP implementation guide. **NOW SUPERSEDED** by operational ogc_features/ module.

**Original Goal**: Replace ArcGIS Enterprise Feature Services with modern, standards-based REST APIs

**Key Goals Achieved**:
- OGC API-Features Core compliance ✅
- Intelligent on-the-fly geometry optimization ✅
- Sub-200ms response times with CDN caching ✅
- 60-80% file size reduction vs. raw PostGIS output ✅
- Support for custom projections (Equal Earth, etc.) ✅

**Architecture Implemented**:
- Azure Front Door Premium (CDN + Cache, 99% requests from cache ~20ms)
- Azure Function App (Premium - No Cold Start)
- PostGIS (Azure PostgreSQL Flexible Server)
- ST_SimplifyPreserveTopology() for generalization
- ST_ReducePrecision() for coordinate quantization
- ST_AsGeoJSON() for output

**Current Status**:
- ✅ FULLY OPERATIONAL - ogc_features/ module (2,600+ lines)
- ✅ Browser tested (30 OCT 2025)
- ✅ 7 vector collections available
- ✅ Direct PostGIS queries with GeoJSON serialization

**Better Current Docs**:
- ogc_features/README.md (comprehensive implementation guide)
- docs/API_DOCUMENTATION.md (unified API reference, 10 NOV 2025)

**Why ARCHIVE**: Implementation complete, better docs exist, design doc served its purpose

---

## 📂 docs/architecture/ (7 files - Core Architecture)

### docs/architecture/COREMACHINE_DESIGN.md
**Status**: 🔶 ACTIVE - Core architecture reference
**Date**: 30 SEP 2025
**Category**: ARCHITECTURE, REFERENCE

**Summary**:
Design document explaining how CoreMachine avoids the "God Class" anti-pattern through composition and delegation.

**The Problem** (Epoch 3):
- BaseController: 2,290 lines, 34 methods - did everything
- Tight coupling (created all dependencies internally)
- Mixed generic orchestration with job-specific business logic
- Hard to test, not reusable, not swappable

**The Solution** (Epoch 4 - CoreMachine):
1. **Composition Over Inheritance** - Receives dependencies, doesn't create them
2. **Single Responsibility** - Only coordinates, delegates everything else
3. **Stateless Coordination** - No job-specific state in CoreMachine
4. **Delegation Pattern** - Workflow lookup → Registry, Task execution → Handler, Database → StateManager

**Key Principles**:
- CoreMachine coordinates but doesn't execute
- Workflows declare stages but don't run them
- Tasks execute business logic but don't orchestrate
- StateManager handles all database operations
- Repositories handle external services (Service Bus, Blob Storage)

**Result**: CoreMachine is ~490 lines, 12 methods (vs BaseController 2,290 lines, 34 methods)
**Reduction**: -78.6% lines, -64.7% methods

**Why This Matters**: Separates "what to do" (job-specific) from "how to orchestrate" (generic machinery)

---

### docs/architecture/COREMACHINE_IMPLEMENTATION.md
**Status**: ✅ COMPLETED - Implementation summary
**Date**: 30 SEP 2025
**Category**: ARCHITECTURE, HISTORICAL

**Summary**:
Complete implementation summary of CoreMachine - the universal job orchestrator for Epoch 4.

**Size Comparison**:
- BaseController (God Class): 2,290 lines, 34 methods, inheritance pattern
- CoreMachine (Coordinator): ~490 lines, 6 public + 6 private methods, composition pattern
- Reduction: -78.6% lines, -64.7% methods

**Key Principles Implemented**:
1. **Composition Over Inheritance** - Dependencies injected, not created internally
2. **Single Responsibility** - CoreMachine only coordinates, doesn't execute business logic
3. **Delegation Pattern** - Workflow → Registry, Task → Handler, Database → StateManager
4. **Stateless Coordination** - All state in database via StateManager, every operation retryable

**Public Interface** (6 methods):
1. `process_job_message()` - Process job queue message, create/queue stage tasks
2. `process_task_message()` - Execute task, handle results, check stage completion
3. `handle_task_completion()` - Handle task completion, update status
4. `check_stage_completion()` - Check if all stage tasks complete
5. `advance_stage()` - Move job to next stage
6. `complete_job()` - Finalize job, aggregate results

**Test Results**: ✅ All tests passing (30 SEP 2025)
**Status**: Production-ready, operational since Epoch 4 transition

---

### docs/architecture/DATABASE_CONNECTION_STRATEGY.md
**Status**: ✅ APPROVED - Current implementation
**Date**: 3 OCT 2025
**Category**: ARCHITECTURE, INFRASTRUCTURE

**Summary**:
Architecture Decision Record: Why we use single-use database connections (not connection pooling) for PostgreSQL.

**Decision**: Single-use connections with immediate cleanup - the CORRECT pattern for our async ETL workload.

**Current Implementation**:
Every database operation: Open connection → Execute → Close → Repeat (75ms overhead per operation)

**Why This Is Correct**:
1. **Async ETL Processing** - Not real-time API, users not waiting
2. **Long-Running Tasks** - 10-300 seconds execution time, 75ms overhead = 0.25% (negligible!)
3. **Bursty Workload** - Unpredictable spikes, don't want idle connections
4. **Azure Functions Serverless** - Cold starts, parallel scaling, connection lifecycle unclear

**Comparison**:
- PostgreSQL: Single-use connections (acceptable for long tasks)
- Service Bus: Singleton with persistent client (reused across operations)

**Benefits**: No connection leak risk, automatic recovery, no stale connections, no pooling complexity

**When to Reconsider**: If we move to real-time API with <100ms response times (not our use case)

---

### docs/architecture/INFRASTRUCTURE_EXPLAINED.md
**Status**: 🔶 ACTIVE - Infrastructure patterns
**Date**: 30 SEP 2025
**Category**: ARCHITECTURE, INFRASTRUCTURE

**Summary**:
Explains why 38 files are categorized as "INFRASTRUCTURE" - the core plumbing both Epoch 3 and Epoch 4 depend on.

**Definition**: Infrastructure = Foundational services that work with any architecture (not epoch-specific)

**Three Main Categories**:

**1. Database Layer** (14 files):
- Core Models: JobRecord, TaskRecord, JobStatus/TaskStatus enums, TaskResult, JobExecutionContext
- Core Operations: StateManager (state transitions), OrchestrationManager (dynamic task creation), CoreController (minimal base ABC)
- Used by: Both epochs for PostgreSQL operations

**2. Schema Definitions** (6 files):
- Pydantic schemas for validation and data flow (NOT database storage)
- Queue message schemas, workflow definitions, SQL generation, update operations
- Used by: Schema deployment, database ops, both epochs

**3. Repository Layer** (9 files):
- Access to Azure resources (Service Bus, Blob Storage, PostgreSQL)
- BaseRepository ABC, specific repositories for each service
- Used by: Both epochs for external service access

**Key Insight**: These files are stable and reusable across architecture shifts
**Analogy**: Epoch 3/4 = Different car models, Infrastructure = The road system both drive on

---

### docs/architecture/INFRASTRUCTURE_RECATEGORIZED.md
**Status**: 🔶 ACTIVE - Infrastructure reorganization
**Date**: 30 SEP 2025
**Category**: ARCHITECTURE, INFRASTRUCTURE

**Summary**:
Proposes replacing vague "INFRASTRUCTURE" category with clear, descriptive categories for better organization.

**Problem**: 38 files lumped together with no clarity on actual purpose

**NEW CATEGORIES (Proposed)**:

**1. DATA MODELS - DATABASE ENTITIES** (7 files):
- Pydantic models that map directly to PostgreSQL tables
- JobRecord (jobs table), TaskRecord (tasks table), JobStatus/TaskStatus (enums)
- Example: `db.insert(JobRecord(...))` - inserts into PostgreSQL

**2. SCHEMAS - DATA VALIDATION & TRANSFORMATION** (6 files):
- Pydantic models for validation, serialization, business logic (NOT stored in DB)
- Queue messages, workflow definitions, SQL generation, update operations
- Example: `JobQueueMessage` (serialized to queue), `TaskUpdateModel` (partial update)

**3. DATABASE OPERATIONS - STATE MANAGEMENT** (7 files):
- StateManager, OrchestrationManager, CoreController, transition logic
- Handles database state changes and orchestration

**4. REPOSITORIES - EXTERNAL SERVICES** (9 files):
- Azure Service Bus, Blob Storage, PostgreSQL connections
- BaseRepository ABC with service-specific implementations

**5. STAC - SPECIALIZED FUNCTIONALITY** (9 files):
- pgSTAC integration, metadata catalog operations
- Separate from core orchestration

**Purpose**: Better organization, clearer responsibilities, easier navigation

---

### docs/architecture/ARCHITECTURE_REFACTOR_COMPLETE.md
**Status**: ✅ COMPLETED - Refactoring summary
**Date**: 1 OCT 2025
**Category**: HISTORICAL, ARCHITECTURE

**Summary**:
Documents completed architecture refactoring implementing **Data-Behavior Separation** pattern using **Composition over Inheritance**.

**What Changed**:

**1. Created Base Data Contracts** (core/contracts/__init__.py):
- `TaskData` - Essential task properties (task_id, parent_job_id, job_type, task_type, stage, parameters)
- `JobData` - Essential job properties (job_id, job_type, parameters)
- Base contracts define "what is this entity"

**2. Refactored Database Models**:
- Changed `TaskRecord(BaseModel)` → `TaskRecord(TaskData)` - inherits base contract
- Changed `JobRecord(BaseModel)` → `JobRecord(JobData)` - inherits base contract
- Only add database-specific fields (status, created_at, updated_at)
- Eliminates field duplication

**3. Refactored Queue Messages**:
- Changed `TaskQueueMessage(BaseModel)` → `TaskQueueMessage(TaskData)` - inherits base contract
- Changed `JobQueueMessage(BaseModel)` → `JobQueueMessage(JobData)` - inherits base contract
- Only add transport-specific fields (retry_count, timestamp)

**4. Renamed Behavior Contract**:
- Renamed `Task` → `TaskExecutor` for clarity
- Separates data (TaskData) from behavior (TaskExecutor)

**Benefits**:
- Single source of truth for entity definitions
- Clear separation: data contracts (what) vs. behavior (how)
- Composition over inheritance pattern
- Easier to maintain, test, extend

---

### docs/architecture/core_machine.md
**Status**: 🔶 ACTIVE - CoreMachine vision
**Date**: 29 SEP 2025
**Category**: ARCHITECTURE, REFERENCE

**Summary**:
Vision for abstracting ALL orchestration machinery into core classes, leaving job-specific code as pure declarations.

**Fundamental Principle**: Job-specific code should be declarative instructions, not imperative machinery

**The Problem** (Current State):
- Job controllers contain ~1,000 lines of orchestration code
- Same machinery repeated in EVERY controller (stage advancement, completion, batching, error handling)
- Only ~50 lines are actually job-specific logic
- Violates DRY principle, makes job creation complex

**The Vision** (Pure Declaration):
- Job-specific files reduced to ~50 lines total
- Declarative stage definitions (WHAT to do, not HOW)
- Stage configuration: parallelism, dependencies, task types
- Parameter schemas with validation
- Business logic handlers in separate files (pure functions, no orchestration)

**Example**:
```python
class HelloWorldJob:
    STAGES = [
        {"number": 1, "name": "greeting", "task_type": "hello_world_greeting"},
        {"number": 2, "name": "reply", "depends_on": 1, "uses_lineage": True}
    ]
    def create_tasks_for_stage(stage, params): ...  # Only custom logic
```

**Benefits**:
- 95% less code per job
- No orchestration machinery in job files
- CoreMachine handles all "how", jobs declare "what"
- Easier to create new jobs (just declare stages)

**Status**: Vision document, guides Epoch 4 CoreMachine implementation

---

## 📂 docs/archive/ (40 files - Historical Analysis)

**Purpose**: Historical analysis documents, cleanup reports, obsolete planning docs
**Organization**: Categorized into analysis/, basecontroller/, cleanup_oct2025/, completed/, obsolete/, planning/, service_bus/
**Status**: All HISTORICAL - valuable for understanding evolution but not current system

---

### docs/archive/analysis/ (4 files)

**Focus**: System analysis and debugging from development period

1. **BASECONTROLLER_ANNOTATED_REFACTOR.md** - Annotated analysis of BaseController refactoring strategy
2. **active_tracing.md** - Active tracing patterns for debugging distributed workflows
3. **postgres_comparison.md** - PostgreSQL vs Azure Storage Tables comparison analysis
4. **stuck_task_analysis.md** - Analysis of stuck task issues and resolution strategies

**Key Insight**: Documents troubleshooting patterns that led to current architecture decisions

---

### docs/archive/basecontroller/ (2 files)

**Focus**: BaseController (Epoch 3) refactoring strategies

1. **BASECONTROLLER_REFACTORING_STRATEGY.md** - Strategy for refactoring 2,290-line God Class
2. **BASECONTROLLER_SPLIT_STRATEGY.md** - Plans for splitting BaseController into components

**Historical Context**: Led to Epoch 4 CoreMachine with composition pattern (490 lines, -78.6% reduction)

---

### docs/archive/cleanup_oct2025/ (10 files)

**Focus**: October 2025 codebase cleanup campaign

**Major Cleanup Reports**:
- **CLEANUP_SUMMARY.md**, **CLEANUP_SUMMARY_4OCT2025.md**, **FINAL_CLEANUP_SUMMARY.md** - Multi-phase cleanup tracking
- **ROOT_FILES_ANALYSIS.md**, **ROOT_FILES_CLEANUP_RECOMMENDATIONS.md**, **ROOT_FOLDERS_ANALYSIS.md** - Root directory organization

**Architecture Analysis**:
- **INTERFACES_ARCHITECTURE_ANALYSIS.md**, **INTERFACES_FOLDER_FINDINGS.md** - Interface pattern analysis
- **REPOSITORIES_VS_INFRASTRUCTURE_ANALYSIS.md** - Repository layer organization decisions
- **PROJECT_INVENTORY.md** - Complete project file inventory

**Result**: Cleaner codebase, better organization, 50+ files archived

---

### docs/archive/completed/ (8 files)

**Focus**: Completed features and resolved issues (note: different from docs/completed/)

**Key Documents**:
- **ABC_ENFORCEMENT_OPPORTUNITIES.md** - Abstract Base Class enforcement patterns
- **COREMACHINE_STATUS_TRANSITION_FIX.md** - CoreMachine status transition bug fix
- **DIAMOND_PATTERN_TEST.md** - Diamond inheritance pattern testing
- **FINAL_STATUS_24OCT2025.md** - System status snapshot (24 OCT 2025)
- **PHASE_2_DEPLOYMENT_GUIDE.md** - Epoch 4 Phase 2 deployment guide
- **PYTHON_HEADER_REVIEW_TRACKING.md** - Python file header standardization tracking
- **QUICK_FIX_GUIDE.md** - Quick reference for common fixes
- **ROOT_CLEANUP_ANALYSIS.md** - Root directory cleanup analysis

**Value**: Completed work documentation, historical snapshots, deployment guides

---

### docs/archive/obsolete/ (2 files)

**Focus**: Obsolete BaseController analysis (Epoch 3 artifacts)

1. **BASECONTROLLER_COMPLETE_ANALYSIS.md** - Complete BaseController analysis (2,290 lines)
2. **BASECONTROLLER_SPLIT_ANALYSIS.md** - BaseController split analysis

**Status**: OBSOLETE - Replaced by Epoch 4 CoreMachine (composition pattern)

---

### docs/archive/planning/ (4 files)

**Focus**: Early planning documents (now implemented or superseded)

1. **ARCHITECTURE_REVIEW.md** - Early architecture review
2. **POSTGRES_REQUIREMENTS.md** - PostgreSQL requirements (see docs/postgres_managed_identity.md for current)
3. **STAC_IMPLEMENTATION_PLAN.md** - Early STAC implementation plan (now operational)
4. **VECTOR_ETL_IMPLEMENTATION_PLAN.md** - Vector ETL implementation plan (OGC Features now live)

**Status**: Plans implemented, better current docs exist

---

### docs/archive/service_bus/ (10 files)

**Focus**: Service Bus implementation journey (Sept-Oct 2025)

**Implementation Documents**:
- **SERVICE_BUS_AZURE_CONFIG.md** - Azure Service Bus configuration
- **SERVICE_BUS_CLEAN_ARCHITECTURE.md** - Clean architecture patterns
- **SERVICE_BUS_COMPLETE_IMPLEMENTATION.md** - Complete implementation summary
- **SERVICE_BUS_IMPLEMENTATION_STATUS.md** - Implementation status tracking
- **SERVICE_BUS_PARALLEL_IMPLEMENTATION.md** - Parallel processing patterns

**Batch Processing**:
- **BATCH_COORDINATION_STRATEGY.md** - Batch coordination strategy
- **BATCH_PROCESSING_ANALYSIS.md** - Batch processing analysis
- **SIMPLIFIED_BATCH_COORDINATION.md** - Simplified batch coordination

**Historical Context**: Documents migration from Azure Storage Queues → Service Bus (COMPLETE 25 OCT 2025)

---

### docs/archive/ Index Files

**ARCHIVE_INDEX.md** - Categorical index of archived documents
**README.md** - Archive folder explanation and purpose

---

---

## 📂 docs/completed/ (50 files - Completed Features)

**Purpose**: Documentation for completed features, migrations, and resolved issues
**Organization**: architecture/, epoch/, migrations/, platform/, reviews/, stac/, stac_strategy/, vector/
**Status**: All ✅ COMPLETED - features implemented, migrations done, issues resolved
**Value**: Historical reference for understanding implementation decisions

---

### docs/completed/architecture/ (11 files)

**Focus**: Completed architecture transitions and patterns

**Key Architecture Documents**:
1. **ARCHITECTURE_DATA_BEHAVIOR_SEPARATION.md** - Data/Behavior separation implementation (composition pattern)
2. **EPOCH4_JOB_ORCHESTRATION_PLAN.md** - Epoch 4 job orchestration complete plan
3. **TASK_REGISTRY_PATTERN.md** - Task registry pattern implementation (decorator-based job registration)
4. **JOB_INJECTION_PATTERN_TLDR.md** - Job injection pattern quick reference

**STAC Implementation**:
5. **STAC_INFRASTRUCTURE_IMPLEMENTATION.md** - STAC infrastructure implementation
6. **STAC_PYDANTIC_INTEGRATION.md** - STAC Pydantic model integration

**Other Completed Work**:
7. **CONTAINER_OPERATIONS_IMPLEMENTATION_PLAN.md** - Container operations implementation
8. **SERVICE_BUS_EXECUTION_TRACE.md** - Service Bus execution tracing
9. **ROOT_MARKDOWN_SUMMARY.md** - Root markdown files summary
10. **markdown_analysis.md**, **markdown_analysis_revised.md** - Documentation cleanup analysis (11 NOV 2025)

**Key Achievement**: Epoch 4 architecture fully implemented with composition pattern

---

### docs/completed/epoch/ (14 files)

**Focus**: Epoch 3→4 transition documentation (Sept-Oct 2025)

**Historical Baseline**:
- **EPOCH3.md** (32KB) - Complete Epoch 3 architecture documentation (BaseController pattern)
- **EPOCH3_INVENTORY.md** - Epoch 3 file inventory

**Epoch 4 Implementation**:
- **EPOCH4_IMPLEMENTATION.md** - Complete Epoch 4 implementation summary
- **EPOCH4_DEPLOYMENT_READY.md** - Deployment readiness checklist (30 SEP 2025 - PASSED)
- **EPOCH4_FOLDER_STRUCTURE.md** - Epoch 4 folder organization
- **EPOCH4_STRUCTURE_ALIGNMENT.md** - Structure alignment verification
- **epoch4_framework.md** (32KB) - Complete Epoch 4 framework documentation

**Phase Summaries**:
- **EPOCH4_PHASE1_SUMMARY.md** - Phase 1: Core architecture (COMPLETE)
- **EPOCH4_PHASE2_SUMMARY.md** - Phase 2: Service Bus integration (COMPLETE)
- **EPOCH4_PHASE3_PARTIAL_SUMMARY.md** - Phase 3: Partial summary
- **PHASE4_COMPLETE.md**, **PHASE_4_COMPLETE.md** - Phase 4: Final implementation (COMPLETE)

**Audit & Headers**:
- **EPOCH_FILE_AUDIT.md** - Complete file audit
- **EPOCH_HEADERS_COMPLETE.md** - Header standardization complete

**Status**: Epoch 4 transition COMPLETE, Epoch 4 is CURRENT system (since Sept-Oct 2025)

---

### docs/completed/migrations/ (6 files)

**Focus**: Completed migrations (all 25 OCT 2025)

1. **STORAGE_QUEUE_DEPRECATION_COMPLETE.md** - Azure Storage Queues → Service Bus migration (COMPLETE)
2. **CORE_SCHEMA_MIGRATION.md** - Core schema migration to PostgreSQL (COMPLETE)
3. **FUNCTION_APP_CLEANUP_COMPLETE.md** - Function app cleanup and consolidation (COMPLETE)
4. **HEALTH_ENDPOINT_CLEANUP_COMPLETE.md** - Health endpoint cleanup (COMPLETE)
5. **DEPRECATED_FILES_ANALYSIS.md** - Analysis of deprecated files
6. **ROOT_MD_FILES_ANALYSIS.md** - Root markdown files migration analysis

**Key Achievement**: All major migrations completed by 25 OCT 2025

---

### docs/completed/platform/ (8 files)

**Focus**: Platform layer implementation and fixes

**Platform Implementation**:
1. **PLATFORM_HELLO_WORLD.md** - Platform layer Hello World example
2. **PLATFORM_BOUNDARY_ANALYSIS.md** - Platform/CoreMachine boundary analysis
3. **PLATFORM_LAYER_FIXES_TODO.md** - Platform layer fixes tracking

**Schema & Patterns**:
4. **PLATFORM_SCHEMA_COMPARISON.md** - Platform vs CoreMachine schema comparison
5. **PLATFORM_SCHEMA_MIGRATION_29OCT2025.md** - Platform schema migration (29 OCT 2025)
6. **PLATFORM_PYDANTIC_ENUM_PATTERNS.md** - Pydantic enum patterns for platform
7. **PLATFORM_SQL_COMPOSITION_COMPLETE.md** - SQL composition pattern implementation (psycopg.sql)

**Research**:
8. **PLATFORM_OPENAPI_RESEARCH_FINDINGS.md** - OpenAPI integration research

**Status**: Platform layer operational with two-layer architecture (Platform → CoreMachine)

---

### docs/completed/reviews/ (3 files)

**Focus**: Code quality reviews and assessments

1. **CODE_QUALITY_REVIEW_29OCT2025.md** - Comprehensive code quality review (29 OCT 2025)
2. **STORAGE_CONFIG_REVIEW_29OCT2025.md** - Storage configuration review (29 OCT 2025)
3. **PHASE1_DOCUMENTATION_REVIEW.md** - Phase 1 documentation review

**Value**: Quality benchmarks, improvement tracking, standards documentation

---

### docs/completed/stac/ (4 files)

**Focus**: STAC API implementation

1. **STAC-INTEGRATION-GUIDE.md** - STAC integration guide
2. **STAC-API-LANDING-PAGE.md** - STAC API landing page implementation
3. **STAC-ETL-FIX.md** - STAC ETL fixes
4. **STAC_ANALYSIS_29OCT2025.md** - STAC analysis (29 OCT 2025)

**Status**: STAC API implemented (pgstac/ module), currently needs refactoring

---

### docs/completed/stac_strategy/ (3 files)

**Focus**: STAC implementation strategy decisions

1. **STAC_COLLECTION_STRATEGY.md** - STAC collection organization strategy
2. **STAC_METADATA_EXTRACTION_STRATEGY.md** - Metadata extraction strategy
3. **STAC_VECTOR_DATA_STRATEGY.md** - Vector data strategy (decided: OGC Features for vectors, STAC for metadata only)

**Key Decision**: Use OGC Features API for vector queries, STAC only for metadata catalog

---

### docs/completed/vector/ (1 file)

**Focus**: Vector workflow implementation

1. **VECTOR_WORKFLOW_GAP_ANALYSIS.md** - Vector workflow gap analysis

**Status**: OGC Features API fully operational (ogc_features/ module, 2,600+ lines)

---

### docs/completed/README.md

**Purpose**: Explains completed/ folder structure and organization
**Categories**: 8 subdirectories, 50 files total
**Date Range**: September-November 2025

---

---

## 🎯 Reading Recommendations by Role

### New Developer Onboarding
1. docs/ARCHITECTURE_QUICKSTART.md (5 min)
2. docs/API_DOCUMENTATION.md (10 min)
3. docs_claude/CLAUDE_CONTEXT.md (20 min)
4. README.md - Job creation tutorial (30 min)

### Understanding Architecture Evolution
1. docs/completed/epoch/EPOCH3.md (historical baseline)
2. docs/completed/epoch/EPOCH4_IMPLEMENTATION.md (current system)
3. docs/architecture/COREMACHINE_DESIGN.md (orchestration engine)

### Deploying to Production
1. docs/postgres_managed_identity.md (database setup)
2. docs/API_DOCUMENTATION.md (API reference)
3. docs_claude/DEPLOYMENT_GUIDE.md (deployment procedures)

### Understanding Design Decisions
1. docs/completed/architecture/TASK_REGISTRY_PATTERN.md (job injection)
2. docs/completed/architecture/ARCHITECTURE_DATA_BEHAVIOR_SEPARATION.md (composition pattern)
3. docs/completed/stac_strategy/ (3 files - STAC decisions)

---

## 📊 Documentation Statistics

**Total Files**: 107 markdown files
**Active Documentation**: ~15 files (docs/, docs/reference/, docs/architecture/)
**Completed Features**: 50 files (docs/completed/)
**Historical Archive**: 52 files (docs/archive/)
**Meta-Documentation**: 5 files (cleanup analyses)

**File Size Distribution**:
- Large (>30KB): EPOCH3.md (32KB), epoch4_framework.md (32KB), H3.md (29KB)
- Medium (10-30KB): Most architecture and implementation docs
- Small (<10KB): Analysis and cleanup summary docs

**Date Range**: September 2025 - November 2025 (active development period)

---

## 🔍 Finding Information Quickly

**By Topic**:
- Architecture: docs/architecture/, docs/completed/architecture/
- STAC: docs/completed/stac/, docs/completed/stac_strategy/
- Platform Layer: docs/completed/platform/
- Epoch Transition: docs/completed/epoch/
- Migrations: docs/completed/migrations/
- Service Bus: docs/archive/service_bus/

**By Date**:
- November 2025: Recent cleanup analyses (DOCS_FOLDER_ANALYSIS.md, etc.)
- October 2025: Platform migrations, OGC Features, code reviews
- September 2025: Epoch 3→4 transition, Service Bus implementation

**By Status**:
- ACTIVE: docs/, docs/reference/, docs/architecture/
- COMPLETED: docs/completed/
- HISTORICAL: docs/archive/

---

**Document Status**: ✅ COMPLETE - All 107 files cataloged with summaries (21 detailed + 86 categorical)
**Completion Date**: 11 NOV 2025
**Coverage**: All docs/ folders (root, reference, architecture, archive, completed)

**Note**: This is a living document - summaries will be added incrementally as files are read and analyzed.