# File Catalog

**Date**: 21 SEP 2025
**Total Python Files**: 47
**Purpose**: Quick file lookup with one-line descriptions

## 🎯 Core Entry Points (2 files)

| File | Purpose |
|------|---------|
| `function_app.py` | Azure Functions entry point - HTTP, Queue, Timer triggers |
| `config.py` | Strongly typed configuration with Pydantic v2 |

## 🎛️ Controllers (5 files)

| File | Purpose |
|------|---------|
| `controller_base.py` | Abstract base controller for Job→Stage→Task orchestration |
| `controller_factories.py` | JobFactory and JobRegistry for controller instantiation |
| `controller_container.py` | Container workflow for blob container file listing |
| `controller_hello_world.py` | Example 2-stage workflow implementation |
| `controller_stac_setup.py` | STAC setup controller for PostGIS/pgstac |

## 📜 Interfaces (1 file)

| File | Purpose |
|------|---------|
| `interface_repository.py` | Pure abstract base classes for repository contracts |

## 💾 Repositories (6 files)

| File | Purpose |
|------|---------|
| `repository_base.py` | Common repository patterns and validation |
| `repository_factory.py` | Central factory for all repository instances |
| `repository_jobs_tasks.py` | Business logic for job and task management |
| `repository_postgresql.py` | PostgreSQL-specific implementation with psycopg |
| `repository_blob.py` | Azure Blob Storage operations |
| `repository_vault.py` | Azure Key Vault integration (currently disabled) |

## ⚙️ Services (4 files)

| File | Purpose |
|------|---------|
| `service_factories.py` | Task handler registry and factory implementation |
| `service_hello_world.py` | Hello World task processing logic |
| `schema_manager.py` | PostgreSQL schema deployment and validation |
| `service_stac_setup.py` | STAC setup service implementation |

## 📋 Schemas (6 files)

| File | Purpose |
|------|---------|
| `schema_base.py` | Core Pydantic models (JobRecord, TaskRecord) |
| `schema_queue.py` | Queue message schemas (JobQueueMessage, TaskQueueMessage) |
| `schema_sql_generator.py` | Converts Pydantic models to PostgreSQL DDL |
| `schema_workflow.py` | Workflow and stage definitions |
| `schema_core.py` | Parameter validation schemas |
| `schema_orchestration.py` | Orchestration contracts (StageResult, etc.) |

## 🔌 Triggers (7 files)

| File | Purpose |
|------|---------|
| `trigger_http_base.py` | Base class for all HTTP triggers |
| `trigger_submit_job.py` | Job submission endpoint `/api/jobs/{job_type}` |
| `trigger_get_job_status.py` | Job status retrieval `/api/jobs/status/{job_id}` |
| `trigger_health.py` | System health check `/api/health` |
| `trigger_db_query.py` | Database query endpoints `/api/db/*` |
| `trigger_poison_monitor.py` | Poison queue monitoring `/api/monitor/poison` |
| `trigger_schema_pydantic_deploy.py` | Schema deployment `/api/db/schema/redeploy` |

## 🛠️ Utilities (3 files)

| File | Purpose |
|------|---------|
| `util_import_validator.py` | Auto-discovery import validation system |
| `contract_validator.py` | Contract enforcement decorator (@enforce_contract) |
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

## 📁 Legacy Documentation (root directory)

| File | Status |
|------|---------|
| `CLAUDE.md` | Redirects to /docs_claude |
| `ARCHITECTURE_CORE.md` | Superseded by ARCHITECTURE_REFERENCE.md |
| `ARCHITECTURE_FILE_INDEX.md` | Superseded by FILE_CATALOG.md |
| `TODO.md` | Split into TODO_ACTIVE.md and HISTORY.md |
| `POSTGRESQL_WORKFLOW_IMPLEMENTATION.md` | Reference only |
| `claude_log_access.md` | Moved to DEPLOYMENT_GUIDE.md |

## 🔧 Utility Scripts

| File | Purpose |
|------|---------|
| `FIX_APP_SETTINGS.sh` | Azure Function App configuration script |
| `fix_sql_functions.py` | PostgreSQL function repair utility |

## 📦 Archives

| File | Purpose |
|------|---------|
| `Archive.zip` | Previous implementation versions |
| `webapp_logs.zip` | Historical debugging logs |

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