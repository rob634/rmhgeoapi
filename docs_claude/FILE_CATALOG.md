# File Catalog

**Date**: 25 SEP 2025
**Total Python Files**: 34 (excluding test files)
**Purpose**: Quick file lookup with one-line descriptions
**Author**: Robert and Geospatial Claude Legion
**Status**: Services successfully migrated to services/ folder

## 🎯 Core Entry Points (2 files)

| File | Purpose |
|------|---------|
| `function_app.py` | Azure Functions entry point - HTTP, Queue, Timer triggers |
| `config.py` | Strongly typed configuration with Pydantic v2 |

## 🎛️ Controllers (6 files)

| File | Purpose |
|------|---------|
| `controller_base.py` | Abstract base controller for Job→Stage→Task orchestration |
| `controller_factories.py` | JobFactory for controller instantiation |
| `controller_container.py` | Container workflow for blob container file listing |
| `controller_hello_world.py` | Example 2-stage workflow implementation |
| `controller_stac_setup.py` | STAC setup controller for PostGIS/pgstac |
| `registration.py` | JobCatalog and TaskCatalog for explicit registration |

## 📜 Interfaces (1 file in interfaces/ folder)

| File | Purpose |
|------|---------|
| `interfaces/repository.py` | IQueueRepository and other repository interfaces |

## 💾 Repositories (7 files in repositories/ folder)

| File | Purpose |
|------|---------|
| `repositories/base.py` | Common repository patterns and validation |
| `repositories/factory.py` | Central factory for all repository instances |
| `repositories/jobs_tasks.py` | Business logic for job and task management |
| `repositories/postgresql.py` | PostgreSQL-specific implementation with psycopg |
| `repositories/blob.py` | Azure Blob Storage operations |
| `repositories/queue.py` | Queue operations with singleton pattern |
| `repositories/vault.py` | Azure Key Vault integration (currently disabled) |

## ⚙️ Services (3 files in services/ folder + 2 in root)

| File | Purpose |
|------|---------|
| `services/service_hello_world.py` | Hello World task processing logic |
| `services/service_blob.py` | Blob storage service handlers |
| `services/service_stac_setup.py` | STAC setup service implementation |
| `task_factory.py` | TaskHandlerFactory and task handler management |
| `schema_manager.py` | PostgreSQL schema deployment and validation |

## 📋 Schemas (6 files)

| File | Purpose |
|------|---------|
| `schema_base.py` | Core Pydantic models (JobRecord, TaskRecord) |
| `schema_queue.py` | Queue message schemas (JobQueueMessage, TaskQueueMessage) |
| `schema_sql_generator.py` | Converts Pydantic models to PostgreSQL DDL |
| `schema_workflow.py` | Workflow and stage definitions |
| `schema_blob.py` | Blob storage related schemas |
| `schema_orchestration.py` | Orchestration contracts (StageResult, etc.) |

## 🔌 Triggers (7 files in triggers/ folder)

| File | Purpose |
|------|---------|
| `triggers/http_base.py` | Base class for all HTTP triggers |
| `triggers/submit_job.py` | Job submission endpoint `/api/jobs/{job_type}` |
| `triggers/get_job_status.py` | Job status retrieval `/api/jobs/status/{job_id}` |
| `triggers/health.py` | System health check `/api/health` |
| `triggers/db_query.py` | Database query endpoints `/api/db/*` |
| `triggers/poison_monitor.py` | Poison queue monitoring `/api/monitor/poison` |
| `triggers/schema_pydantic_deploy.py` | Schema deployment `/api/db/schema/redeploy` |

## 🛠️ Utilities (3 files in utils/ folder + 1 in root)

| File | Purpose |
|------|---------|
| `utils/import_validator.py` | Auto-discovery import validation system |
| `utils/contract_validator.py` | Contract enforcement decorator (@enforce_contract) |
| `util_logger.py` | Enhanced logging factory with correlation IDs |

## 📝 Configuration Files

| File | Purpose |
|------|---------|
| `host.json` | Azure Functions runtime configuration |
| `requirements.txt` | Python package dependencies |
| `local.settings.json` | Local development environment variables |
| `local.settings.example.json` | Template for local settings |

## 📚 Documentation (in /docs_claude)

| File | Purpose |
|------|---------|
| `CLAUDE_CONTEXT.md` | Primary entry point for Claude |
| `TODO_ACTIVE.md` | Current tasks and blocking issues |
| `ARCHITECTURE_REFERENCE.md` | Deep technical specifications |
| `FILE_CATALOG.md` | This file - quick file lookup |
| `DEPLOYMENT_GUIDE.md` | Deployment procedures and monitoring |
| `HISTORY.md` | Completed work log |

## 📁 Documentation (root directory)

| File | Status |
|------|---------|
| `CLAUDE.md` | Redirects to /docs_claude |
| `LOCAL_TESTING_README.md` | Local database testing guide for STAC |

## 🧪 Test Files (10+ files)

| File | Purpose |
|------|---------|
| `test_registration.py` | Unit tests for registration system |
| `test_phase2_registration.py` | Phase 2 registration tests |
| `test_phase3.py` | Phase 3 registration tests |
| `test_phase4_complete.py` | Phase 4 completion tests |
| `test_stac_*.py` | STAC-related test files |
| `test_local_database.py` | Local database testing |
| Other test files | Various unit and integration tests |

## 🔧 Utility Scripts & Configuration

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Local STAC/PostgreSQL testing environment |
| `sql/` folder | SQL scripts and initialization files |

## 📦 Reference Materials (in /reference folder)

| File | Purpose |
|------|---------|
| Deprecated .md files | Historical documentation moved for reference |
| Design documents | Architecture and planning documents |
| `Archive.zip` | Previous implementation versions |

---

## Quick Navigation by Task

### 🔍 Looking for job orchestration?
→ Check `controller_*.py` files

### 🔍 Need to understand data models?
→ Check `schema_*.py` files

### 🔍 Working with database?
→ Check `repository_*.py` files

### 🔍 Adding new endpoints?
→ Check `trigger_*.py` files

### 🔍 Processing business logic?
→ Check `service_*.py` files

---

*For architecture details, see ARCHITECTURE_REFERENCE.md. For current tasks, see TODO_ACTIVE.md.*