# Project Inventory - Complete File & Folder List

**Date**: 4 OCT 2025
**Purpose**: Comprehensive inventory for cleanup review
**Author**: Robert and Geospatial Claude Legion
**Total Items**: 250+ files and folders

> **Next Step**: Review each section and mark items with:
> - ✅ KEEP - Essential for production
> - ⚠️ REVIEW - Needs evaluation
> - ❌ DELETE - Safe to remove

---

## 📁 Root Directory Files

### Configuration Files
- [ ] `.funcignore` - Azure Functions ignore patterns
- [ ] `config.py` - Pydantic configuration
- [ ] `function_app.py` - Main Azure Functions entry point
- [ ] `host.json` - Azure Functions runtime config
- [ ] `requirements.txt` - Python dependencies
- [ ] `local.settings.json` - Local development settings
- [ ] `local.settings.example.json` - Settings template
- [ ] `local.settings.test.json` - Test settings
- [ ] `docker-compose.yml` - Docker configuration

### Documentation Files (Root)
- [ ] `CLAUDE.md` - Primary Claude context (KEEP)
- [ ] `.CLAUDE.md.swp` - Vim swap file (DELETE?)

### Utility Files (Root)
- [ ] `exceptions.py` - Custom exception classes
- [ ] `util_logger.py` - Logging utilities

### Data/Config Files
- [ ] `import_validation_registry.json` - Import health tracking
- [ ] `service_bus.json` - Service Bus config
- [ ] `missing_methods_analysis.txt` - Analysis notes (DELETE?)

### Archive Files
- [ ] `app_logs.zip` - Old logs (DELETE?)
- [ ] `rmhgeoapibeta-logs-latest.zip` - Recent logs (DELETE?)
- [ ] `rmhgeoapibeta-logs.zip` - Old logs (DELETE?)

### System Files
- [ ] `.DS_Store` - macOS system file (DELETE)
- [ ] `.python_packages/` - Azure Functions packages (auto-generated)

---

## 📂 Core Architecture (`core/` - 17 files)

### Core Root
- [ ] `core/__init__.py`
- [ ] `core/machine.py` - CoreMachine orchestration ✅ KEEP
- [ ] `core/task_id.py` - Deterministic task IDs ✅ KEEP
- [ ] `core/utils.py` - Core utilities ✅ KEEP
- [ ] `core/core_controller.py` - Base controller
- [ ] `core/state_manager.py` - State management ✅ KEEP
- [ ] `core/orchestration_manager.py` - Orchestration

### Core Models (`core/models/` - 7 files)
- [ ] `core/models/__init__.py`
- [ ] `core/models/context.py` - Execution context
- [ ] `core/models/enums.py` - JobStatus, TaskStatus ✅ KEEP
- [ ] `core/models/job.py` - Job models ✅ KEEP
- [ ] `core/models/results.py` - Result models ✅ KEEP
- [ ] `core/models/stage.py` - Stage models
- [ ] `core/models/task.py` - Task models ✅ KEEP

### Core Logic (`core/logic/` - 3 files)
- [ ] `core/logic/__init__.py`
- [ ] `core/logic/calculations.py` - Stage calculations
- [ ] `core/logic/transitions.py` - State transitions

### Core Schema (`core/schema/` - 7 files)
- [ ] `core/schema/__init__.py`
- [ ] `core/schema/deployer.py` - Schema deployment ✅ KEEP
- [ ] `core/schema/orchestration.py` - Orchestration schemas
- [ ] `core/schema/queue.py` - Queue message schemas ✅ KEEP
- [ ] `core/schema/sql_generator.py` - SQL DDL generation ✅ KEEP
- [ ] `core/schema/updates.py` - Update models ✅ KEEP
- [ ] `core/schema/workflow.py` - Workflow definitions

### Core Contracts (`core/contracts/` - 1 file)
- [ ] `core/contracts/__init__.py`

---

## 📂 Infrastructure Layer (`infrastructure/` - 9 files)

- [ ] `infrastructure/__init__.py`
- [ ] `infrastructure/base.py` - Base repository ✅ KEEP
- [ ] `infrastructure/blob.py` - Blob storage ✅ KEEP
- [ ] `infrastructure/factory.py` - Repository factory ✅ KEEP
- [ ] `infrastructure/interface_repository.py` - Interfaces ✅ KEEP
- [ ] `infrastructure/interface_repository.py.bak` - Backup (DELETE)
- [ ] `infrastructure/jobs_tasks.py` - Jobs/tasks repo ✅ KEEP
- [ ] `infrastructure/jobs_tasks.py.bak` - Backup (DELETE)
- [ ] `infrastructure/postgresql.py` - PostgreSQL repo ✅ KEEP
- [ ] `infrastructure/postgresql.py.bak` - Backup (DELETE)
- [ ] `infrastructure/queue.py` - Queue storage ✅ KEEP
- [ ] `infrastructure/service_bus.py` - Service Bus ✅ KEEP
- [ ] `infrastructure/vault.py` - Key Vault ✅ KEEP

---

## 📂 Repositories Layer (`repositories/` - 9 files)

- [ ] `repositories/__init__.py`
- [ ] `repositories/base.py` - Base patterns ✅ KEEP
- [ ] `repositories/blob.py` - Blob operations ✅ KEEP
- [ ] `repositories/factory.py` - Factory pattern ✅ KEEP
- [ ] `repositories/interface_repository.py` - Interfaces ✅ KEEP
- [ ] `repositories/jobs_tasks.py` - Business logic ✅ KEEP
- [ ] `repositories/postgresql.py` - PostgreSQL impl ✅ KEEP
- [ ] `repositories/queue.py` - Queue operations ✅ KEEP
- [ ] `repositories/service_bus.py` - Service Bus impl ✅ KEEP
- [ ] `repositories/vault.py` - Vault operations ✅ KEEP

---

## 📂 Job Workflows (`jobs/` - 6 files) ✅ KEEP ALL

- [ ] `jobs/__init__.py` ✅ KEEP
- [ ] `jobs/hello_world.py` ✅ KEEP
- [ ] `jobs/container_list.py` ✅ KEEP (NEW 4 OCT)
- [ ] `jobs/container_summary.py` ✅ KEEP (NEW 4 OCT)
- [ ] `jobs/registry.py` ✅ KEEP
- [ ] `jobs/workflow.py` ✅ KEEP

---

## 📂 Service Handlers (`services/` - 8 files)

- [ ] `services/__init__.py` ✅ KEEP
- [ ] `services/hello_world.py` ✅ KEEP
- [ ] `services/container_list.py` ✅ KEEP (NEW 4 OCT)
- [ ] `services/container_summary.py` ✅ KEEP (NEW 4 OCT)
- [ ] `services/registry.py` ✅ KEEP
- [ ] `services/service_blob.py` ✅ KEEP
- [ ] `services/service_hello_world.py` - Duplicate? (REVIEW)
- [ ] `services/service_stac_setup.py` ✅ KEEP
- [ ] `services/task.py` ✅ KEEP

### Service Backups
- [ ] `service_stac_setup.py.backup` - Root backup file (DELETE)

---

## 📂 HTTP Triggers (`triggers/` - 8 files) ✅ KEEP ALL

- [ ] `triggers/__init__.py`
- [ ] `triggers/db_query.py` - Database queries
- [ ] `triggers/get_job_status.py` - Job status endpoint
- [ ] `triggers/health.py` - Health check
- [ ] `triggers/http_base.py` - Base HTTP handler
- [ ] `triggers/poison_monitor.py` - Poison queue monitor
- [ ] `triggers/schema_pydantic_deploy.py` - Schema deployment
- [ ] `triggers/submit_job.py` - Job submission

---

## 📂 Utilities (`utils/` - 3 files)

- [ ] `utils/__init__.py` ✅ KEEP
- [ ] `utils/contract_validator.py` ✅ KEEP
- [ ] `utils/import_validator.py` ✅ KEEP

---

## 📂 Interfaces (`interfaces/` - 1 file)

- [ ] `interfaces/repository.py` - Repository interfaces (REVIEW - duplicate of infrastructure?)

---

## 📂 SQL Scripts (`sql/` - 1 file)

- [ ] `sql/init/01_init_extensions.sql` - PostgreSQL extensions ✅ KEEP

---

## 📂 Archive Folder (`archive/` - 30+ files)

### Archive Root
- [ ] `archive/.DS_Store` - macOS file (DELETE)
- [ ] `archive/ARCHIVE_README.md` ✅ KEEP

### Archived Controllers
- [ ] `archive/controller_base.py` - Old God Class (REVIEW - reference?)
- [ ] `archive/controller_container.py` - Old container controller
- [ ] `archive/controller_factories.py` - Old factories
- [ ] `archive/controller_hello_world.py` - Old hello world
- [ ] `archive/controller_service_bus.py` - Old service bus
- [ ] `archive/controller_stac_setup.py` - Old STAC
- [ ] `archive/registration.py` - Old registration

### Archived Schemas
- [ ] `archive/schema_base.py` - Legacy base schemas
- [ ] `archive/schema_blob.py` - Legacy blob schemas
- [ ] `archive/schema_manager.py` - Legacy manager
- [ ] `archive/schema_orchestration.py` - Legacy orchestration
- [ ] `archive/schema_queue.py` - Legacy queue schemas
- [ ] `archive/schema_sql_generator.py` - Legacy SQL gen
- [ ] `archive/schema_updates.py` - Legacy updates
- [ ] `archive/schema_workflow.py` - Legacy workflow

### Archived Utilities
- [ ] `archive/service_bus_list_processor.py` - Old processor
- [ ] `archive/task_factory.py` - Old task factory

### Archive Docs (`archive/archive_docs/` - 8 files)
- [ ] `archive/archive_docs/ARCHITECTURE_CORE.md`
- [ ] `archive/archive_docs/ARCHITECTURE_FILE_INDEX.md`
- [ ] `archive/archive_docs/CLAUDE_CONTEXT_HEADER_TRACKING.md`
- [ ] `archive/archive_docs/CONFIGURATION_USAGE.md`
- [ ] `archive/archive_docs/DEPLOYMENT_AND_LOGS_GUIDE.md`
- [ ] `archive/archive_docs/PYDANTIC_REVIEW.md`
- [ ] `archive/archive_docs/README.md`
- [ ] `archive/archive_docs/todo.md`

### Epoch 3 Folders
- [ ] `archive/epoch3_controllers/` - Empty placeholder folders (DELETE)
- [ ] `archive/epoch3_docs/` - Empty placeholder folders (DELETE)
- [ ] `archive/epoch3_schemas/` - Empty placeholder folders (DELETE)
- [ ] `archive/archive_epoch3_schema/` - Empty with .DS_Store (DELETE)

---

## 📂 Documentation (`docs/` - 50+ files)

### Root Docs
- [ ] `docs/ARCHITECTURE_DATA_BEHAVIOR_SEPARATION.md`
- [ ] `docs/CONTAINER_OPERATIONS_IMPLEMENTATION_PLAN.md`
- [ ] `docs/EPOCH4_JOB_ORCHESTRATION_PLAN.md`
- [ ] `docs/SERVICE_BUS_EXECUTION_TRACE.md`

### Architecture Docs (`docs/architecture/` - 7 files)
- [ ] `docs/architecture/ARCHITECTURE_REFACTOR_COMPLETE.md`
- [ ] `docs/architecture/COREMACHINE_DESIGN.md`
- [ ] `docs/architecture/COREMACHINE_IMPLEMENTATION.md`
- [ ] `docs/architecture/DATABASE_CONNECTION_STRATEGY.md`
- [ ] `docs/architecture/INFRASTRUCTURE_EXPLAINED.md`
- [ ] `docs/architecture/INFRASTRUCTURE_RECATEGORIZED.md`
- [ ] `docs/architecture/core_machine.md`

### Archive Analysis (`docs/archive/` - 20+ files)
- [ ] `docs/archive/README.md`

**Analysis Subfolder:**
- [ ] `docs/archive/analysis/BASECONTROLLER_ANNOTATED_REFACTOR.md`
- [ ] `docs/archive/analysis/active_tracing.md`
- [ ] `docs/archive/analysis/postgres_comparison.md`
- [ ] `docs/archive/analysis/stuck_task_analysis.md`

**BaseController Subfolder:**
- [ ] `docs/archive/basecontroller/BASECONTROLLER_REFACTORING_STRATEGY.md`
- [ ] `docs/archive/basecontroller/BASECONTROLLER_SPLIT_STRATEGY.md`

**Obsolete Subfolder:**
- [ ] `docs/archive/obsolete/BASECONTROLLER_COMPLETE_ANALYSIS.md`
- [ ] `docs/archive/obsolete/BASECONTROLLER_SPLIT_ANALYSIS.md`

**Service Bus Subfolder:**
- [ ] `docs/archive/service_bus/BATCH_COORDINATION_STRATEGY.md`
- [ ] `docs/archive/service_bus/BATCH_PROCESSING_ANALYSIS.md`
- [ ] `docs/archive/service_bus/SERVICE_BUS_AZURE_CONFIG.md`
- [ ] `docs/archive/service_bus/SERVICE_BUS_CLEAN_ARCHITECTURE.md`
- [ ] `docs/archive/service_bus/SERVICE_BUS_COMPLETE_IMPLEMENTATION.md`
- [ ] `docs/archive/service_bus/SERVICE_BUS_IMPLEMENTATION_STATUS.md`
- [ ] `docs/archive/service_bus/SERVICE_BUS_PARALLEL_IMPLEMENTATION.md`
- [ ] `docs/archive/service_bus/SIMPLIFIED_BATCH_COORDINATION.md`

### Epoch Docs (`docs/epoch/` - 14 files)
- [ ] `docs/epoch/EPOCH3.md`
- [ ] `docs/epoch/EPOCH3_INVENTORY.md`
- [ ] `docs/epoch/EPOCH4_DEPLOYMENT_READY.md`
- [ ] `docs/epoch/EPOCH4_FOLDER_STRUCTURE.md`
- [ ] `docs/epoch/EPOCH4_IMPLEMENTATION.md`
- [ ] `docs/epoch/EPOCH4_PHASE1_SUMMARY.md`
- [ ] `docs/epoch/EPOCH4_PHASE2_SUMMARY.md`
- [ ] `docs/epoch/EPOCH4_PHASE3_PARTIAL_SUMMARY.md`
- [ ] `docs/epoch/EPOCH4_STRUCTURE_ALIGNMENT.md`
- [ ] `docs/epoch/EPOCH_FILE_AUDIT.md`
- [ ] `docs/epoch/EPOCH_HEADERS_COMPLETE.md`
- [ ] `docs/epoch/PHASE4_COMPLETE.md`
- [ ] `docs/epoch/PHASE_4_COMPLETE.md`
- [ ] `docs/epoch/epoch4_framework.md`

### Migration Docs (`docs/migrations/` - 7 files)
- [ ] `docs/migrations/CORE_IMPORT_TEST_REPORT.md`
- [ ] `docs/migrations/CORE_SCHEMA_MIGRATION.md`
- [ ] `docs/migrations/DEPRECATED_FILES_ANALYSIS.md`
- [ ] `docs/migrations/FUNCTION_APP_CLEANUP_COMPLETE.md`
- [ ] `docs/migrations/HEALTH_ENDPOINT_CLEANUP_COMPLETE.md`
- [ ] `docs/migrations/ROOT_MD_FILES_ANALYSIS.md`
- [ ] `docs/migrations/STORAGE_QUEUE_DEPRECATION_COMPLETE.md`

---

## 📂 Claude Documentation (`docs_claude/` - 14 files) ✅ KEEP ALL

- [ ] `docs_claude/APPLICATION_INSIGHTS_QUERY_PATTERNS.md` ✅ KEEP
- [ ] `docs_claude/ARCHITECTURE_REFERENCE.md` ✅ KEEP
- [ ] `docs_claude/CLAUDE_CONTEXT.md` ✅ KEEP (Primary)
- [ ] `docs_claude/CONTAINER_CONTROLLER_FIX_MEMORY.md` ✅ KEEP
- [ ] `docs_claude/DEPLOYMENT_GUIDE.md` ✅ KEEP
- [ ] `docs_claude/FILE_CATALOG.md` ✅ KEEP
- [ ] `docs_claude/HISTORY.md` ✅ KEEP
- [ ] `docs_claude/OLDER_HISTORY.md` ✅ KEEP
- [ ] `docs_claude/ORCHESTRATION_ANALYSIS.md` ✅ KEEP
- [ ] `docs_claude/SERVICE_BUS_STATUS.md` ✅ KEEP
- [ ] `docs_claude/STAC_RESEARCH.md` ✅ KEEP
- [ ] `docs_claude/TODO_ACTIVE.md` ✅ KEEP
- [ ] `docs_claude/VECTOR_ETL_STRATEGY.md` ✅ KEEP
- [ ] `docs_claude/claude_log_access.md` ✅ KEEP

---

## 📂 Local Testing (`local/` - 30+ files)

### Local Docs
- [ ] `local/CLEANUP_SUMMARY.md`
- [ ] `local/IMPORT_TEST_RESULTS.md`
- [ ] `local/LOCAL_TESTING_README.md` ✅ KEEP
- [ ] `local/__init__.py`

### Local Shell Scripts
- [ ] `local/check_all_activity.sh`
- [ ] `local/check_errors.sh`
- [ ] `local/check_functions.sh`
- [ ] `local/check_logs.sh`
- [ ] `local/check_queue_messages.sh`
- [ ] `local/check_queue_triggers.sh`
- [ ] `local/check_schema_logs.sh`
- [ ] `local/check_service_bus.sh`
- [ ] `local/start_local_test.sh`

### Local Python Scripts
- [ ] `local/controller_service_bus_container.py`
- [ ] `local/controller_service_bus_hello.py`
- [ ] `local/debug_service_bus.py`
- [ ] `local/query_job_completion.py`
- [ ] `local/query_logs.py`
- [ ] `local/query_logs_detailed.py`
- [ ] `local/query_traceback.py`
- [ ] `local/test_core_imports.py`
- [ ] `local/test_core_machine.py`
- [ ] `local/test_deployment_ready.py`
- [ ] `local/test_imports.py`
- [ ] `local/test_local_database.py`
- [ ] `local/test_phase2_registration.py`
- [ ] `local/test_phase3.py`
- [ ] `local/test_phase4_complete.py`
- [ ] `local/test_queue_boundary.py`
- [ ] `local/test_registration.py`
- [ ] `local/test_service_bus_fix.py`
- [ ] `local/test_stac_ingestion_local.py`
- [ ] `local/test_stac_setup_local.py`
- [ ] `local/test_stac_validation.py`
- [ ] `local/test_stage_completion.py`
- [ ] `local/update_epoch_headers.py`
- [ ] `local/update_to_descriptive_categories.py`

---

## 📂 Local Scripts (`local_scripts/` - 8 files)

- [ ] `local_scripts/backup_env_vars.json` - Environment backup
- [ ] `local_scripts/current_env_vars.json` - Current env vars
- [ ] `local_scripts/deploy.sh` - Deployment script ✅ KEEP
- [ ] `local_scripts/fix-zombie-functions.sh`
- [ ] `local_scripts/nuclear-reset.sh`
- [ ] `local_scripts/wipe-wwwroot.sh`

---

## 📂 Local Database (`local_db/` - empty?)

- [ ] `local_db/` - Appears empty (DELETE if empty)

---

## 📂 Reference Documentation (`reference/` - 18 files)

- [ ] `reference/Archive.zip` - Old archive (DELETE?)
- [ ] `reference/GIT_COMPARISON_ANALYSIS.md`
- [ ] `reference/INFRA_CONFIG.md`
- [ ] `reference/QUEUE_MESSAGE_VALIDATION_OUTLINE.md`
- [ ] `reference/STORAGE_OPERATIONS_PLAN.md`
- [ ] `reference/claude_optimization.json`
- [ ] `reference/code_design.json`
- [ ] `reference/consolidated_redesign.md`
- [ ] `reference/contracts.md`
- [ ] `reference/controller_base_analysis.md`
- [ ] `reference/deployment.md`
- [ ] `reference/fromclaude.md`
- [ ] `reference/fromopus.json`
- [ ] `reference/logging.md`
- [ ] `reference/oldvector.py`
- [ ] `reference/redesign.md`
- [ ] `reference/registry.md`
- [ ] `reference/repository.md`
- [ ] `reference/robert_notes.md`

---

## 📂 Test Files (`test/` - 18 files)

### Test JSON
- [ ] `test/test.json`
- [ ] `test/test2.json`
- [ ] `test/test_payload.json`

### Test Scripts
- [ ] `test/test_bigint_casting.py`
- [ ] `test/test_composed_sql_local.py`
- [ ] `test/test_deploy_local.py`
- [ ] `test/test_deployment_readiness.py`
- [ ] `test/test_health_composed.sh`
- [ ] `test/test_health_schema.py`
- [ ] `test/test_local_integration.py`
- [ ] `test/test_repository_basic.py`
- [ ] `test/test_repository_refactor.py`
- [ ] `test/test_signature_fix.py`
- [ ] `test/test_unified_hello.py`
- [ ] `test/test_unified_sql_gen.py`

---

## 📂 Validators (`validators/` - empty?)

- [ ] `validators/` - Appears to be empty directory (DELETE if empty)

---

## 📂 IDE & System Folders

### VSCode
- [ ] `.vscode/extensions.json` ✅ KEEP
- [ ] `.vscode/launch.json` ✅ KEEP
- [ ] `.vscode/settings.json` ✅ KEEP
- [ ] `.vscode/tasks.json` ✅ KEEP

### Claude Code
- [ ] `.claude/settings.local.json` ✅ KEEP

---

## 📊 Summary Statistics

**Total Folders**: ~35
**Total Files**: ~250+

### By Category:
- **Core Architecture**: 17 files ✅ Essential
- **Infrastructure**: 9 files ✅ Essential
- **Repositories**: 9 files ✅ Essential
- **Jobs**: 6 files ✅ Essential
- **Services**: 8 files ✅ Essential
- **Triggers**: 8 files ✅ Essential
- **Utilities**: 3 files ✅ Essential
- **Documentation**: 80+ files ⚠️ Review needed
- **Archive**: 30+ files ⚠️ Can likely delete
- **Local/Test**: 50+ files ⚠️ Review needed
- **Reference**: 18 files ⚠️ Review needed

### Initial Recommendations:

**SAFE TO DELETE (Immediate):**
- `.DS_Store` files (macOS system files)
- `.swp` files (Vim swap files)
- `*.bak` backup files
- Log zip files in root
- Empty placeholder folders (epoch3_*)
- `archive/archive_epoch3_schema/.DS_Store`

**REVIEW NEEDED:**
- Archive folder contents (keep for reference or delete?)
- Test files (move to separate test repo?)
- Local scripts (keep or archive?)
- Reference folder (historical value?)
- Duplicate docs in `docs/` vs `docs_claude/`

**DEFINITELY KEEP:**
- All `core/` files
- All `infrastructure/` files
- All `repositories/` files
- All `jobs/` files
- All `services/` files
- All `triggers/` files
- All `utils/` files
- All `docs_claude/` files
- Root config files (function_app.py, config.py, etc.)
