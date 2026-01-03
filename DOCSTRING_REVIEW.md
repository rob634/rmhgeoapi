# Docstring Review & Hardcoded Variable Audit

**Created**: 02 JAN 2026
**Status**: In Progress
**Purpose**: Review every Python file for docstring accuracy and hardcoded variable elimination

---

## Overview

**Total Active Files**: 275 (excluding `docs/archive/`, `__pycache__`, `.venv`)

### Target Audience

Docstrings must be written for **Claudes and humans working in corporate QA/PROD environments** where:

| DEV Environment (current) | Corporate QA/PROD Environment |
|---------------------------|-------------------------------|
| Personal Azure subscription | Enterprise Azure with governance |
| Portal changes in 5 seconds | Service requests, change tickets |
| Direct CLI access | Limited permissions, RBAC |
| Can experiment freely | Must get it right first time |
| Failures are learning | Failures delay projects |

**The docstrings must answer:** "What do I need to request from IT before deploying?"

### Priority Files for Operational Documentation

These files are **CRITICAL** for QA/PROD deployment and should have comprehensive Check 8 documentation:

| Priority | File | Why Critical |
|----------|------|--------------|
| P0 | `config/defaults.py` | Single source of truth for all required env vars |
| P0 | `config/database_config.py` | PostgreSQL connection, managed identity |
| P0 | `config/storage_config.py` | Storage accounts, SAS tokens, container names |
| P0 | `config/queue_config.py` | Service Bus namespace, connection strings |
| P1 | `infrastructure/postgresql.py` | Database connection pooling, auth |
| P1 | `infrastructure/blob.py` | Blob storage access patterns |
| P1 | `infrastructure/service_bus.py` | Queue messaging |
| P1 | `triggers/health.py` | Health check endpoint (deployment verification) |
| P2 | `function_app.py` | App startup, route registration |
| P2 | `config/app_config.py` | Composed config with all settings |

### Review Criteria

For each file, check:
1. **Module docstring** - Accurate description of purpose
2. **Class docstrings** - Clear explanation of responsibility
3. **Function/method docstrings** - Parameters, returns, raises documented
4. **Hardcoded values** - URLs, paths, container names, schema names, etc.
5. **Magic numbers** - Unexplained numeric constants

### Legend

- [ ] Not reviewed
- [x] Reviewed and updated
- [~] Reviewed, no changes needed
- [!] Needs attention (complex refactor required)

---

## Systematic Review Checklist

**Developed from 3-file sample review (02 JAN 2026)**

For each Python file, apply these 7 checks in order:

### Which Checks Apply to Which Files?

| File Type | Checks 1-6 | Check 7 (Env Vars) | Check 8 (Ops Deployment) |
|-----------|------------|--------------------|-----------------------|
| `config/*` | ✅ All | ✅ Critical | ✅ Critical |
| `infrastructure/*` | ✅ All | ✅ Critical | ✅ Critical |
| `core/*` | ✅ All | If applicable | Usually not |
| `jobs/*` | ✅ All | If applicable | Usually not |
| `services/*` | ✅ All | If applicable | Usually not |
| `triggers/*` | ✅ All | If applicable | Endpoint docs |
| `web_interfaces/*` | ✅ All | Rarely | Rarely |
| `test/*` | Checks 1-4 | No | No |

---

### Check 1: Module Docstring Accuracy

- [ ] **Purpose statement** - Does it accurately describe what the module does?
- [ ] **Structure/contents** - If it lists files or components, do they match reality?
- [ ] **Dependencies** - Are listed dependencies still accurate?
- [ ] **Usage examples** - Do examples still work with current API?
- [ ] **Created/updated dates** - Are dates accurate?

**Common issues found:**
- Outdated file listings (e.g., `config/__init__.py` was missing 6 files)
- Stale usage examples referencing old API

### Check 2: Class/Function Docstrings

- [ ] **Parameters documented** - All params have type hints and descriptions?
- [ ] **Returns documented** - Return type and meaning clear?
- [ ] **Raises documented** - Exceptions listed?
- [ ] **Examples provided** - For complex methods?

### Check 3: Hardcoded Environment-Specific Values

**Search for and eliminate:**
```python
# Azure-specific
"rmhazure_rg"           # → AzureDefaults.RESOURCE_GROUP
"rmhazuregeoapi"        # → AzureDefaults.ETL_APP_URL
"rmhpgflex"             # → DatabaseDefaults or env var

# Container names
"bronze-*", "silver-*"  # → StorageDefaults.BRONZE_*, SILVER_*

# Schema names
"app", "geo", "pgstac"  # → DatabaseDefaults.APP_SCHEMA, etc.
```

**Pattern:** Move to `config/defaults.py` and reference the constant.

### Check 4: Magic Numbers

**Search for unexplained numeric constants:**
```python
# Bad
if file_size > 1200:  # What is 1200?

# Good
if file_size > RasterDefaults.RASTER_ROUTE_LARGE_MB:
```

**Check these categories:**
- Timeouts (seconds/minutes)
- Size limits (MB/GB)
- Retry counts
- Batch sizes
- Port numbers

### Check 5: Outdated Comments

- [ ] `# TODO` comments - Still relevant or done?
- [ ] `# DEPRECATED` - Should code be removed?
- [ ] `# HACK` / `# FIXME` - Can we fix properly now?
- [ ] Date references - e.g., "as of Dec 2024" still accurate?

### Check 6: Import Statement Accuracy

- [ ] Unused imports? (run `ruff` or similar)
- [ ] Imports from moved/renamed modules?
- [ ] Circular import risks?

### Check 7: Environment Variable Documentation

For config files, verify:
- [ ] All env vars listed in docstring actually exist in code
- [ ] All env vars in code are documented in docstring
- [ ] Default values match what's documented

### Check 8: Operational Deployment Documentation (CRITICAL)

**For config-related and infrastructure files, docstrings must answer:**

#### 8.1 Required Resources Checklist
- [ ] **REQUIRED env vars** - What MUST be set before deployment?
- [ ] **OPTIONAL env vars** - What has sensible defaults?
- [ ] **Fail-fast behavior** - What error message appears if missing?

#### 8.2 Service Request Guidance
For each required Azure resource, document:
- [ ] **Resource type** - Managed Identity, Storage Account, Key Vault, etc.
- [ ] **Naming convention** - What should it be called?
- [ ] **Required permissions/roles** - RBAC roles, scopes
- [ ] **Dependencies** - What must exist first?

**Example of good operational docstring:**
```python
"""
PostgreSQL Managed Identity Configuration.

REQUIRED - Must be configured before deployment:

    Environment Variable: DB_ADMIN_MANAGED_IDENTITY_NAME

    Service Request Template:
    -------------------------
    "Create User-Assigned Managed Identity:
     - Name: {app-name}-db-admin
     - Resource Group: {your-rg}
     - Role Assignment: 'Azure AD Authentication Administrator'
     - Scope: PostgreSQL Flexible Server '{server-name}'

     After creation, add to Function App:
     - Settings > Identity > User Assigned > Add"

    Fail-fast Behavior:
    -------------------
    If not set, app crashes at startup with:
    'STARTUP_FAILED: DB_ADMIN_MANAGED_IDENTITY_NAME not configured'

    Verification:
    -------------
    curl https://{app-url}/api/health
    # Should show: "database": {"status": "healthy"}
"""
```

#### 8.3 DEV vs QA/PROD Differences
- [ ] **Placeholder values** - Which defaults are DEV-only and MUST be replaced?
- [ ] **Network requirements** - VNet integration, private endpoints?
- [ ] **Security requirements** - Key Vault vs env vars, managed identity vs connection strings?

#### 8.4 Deployment Verification
- [ ] **Health check endpoints** - How to verify component is working?
- [ ] **Expected log messages** - What indicates success?
- [ ] **Common failure modes** - What breaks and how to fix?

---

## Patterns and Templates (Learned from P0 Review)

**Extracted from Sessions 1-4 reviewing defaults.py, database_config.py, storage_config.py, queue_config.py**

### Pattern 1: Module Docstring Structure

All P0 config files now follow this consistent structure:

```python
"""
{Module Title}.

================================================================================
CORPORATE QA/PROD DEPLOYMENT GUIDE
================================================================================

{Brief description of what this module configures.}

--------------------------------------------------------------------------------
REQUIRED AZURE RESOURCES
--------------------------------------------------------------------------------

1. {RESOURCE TYPE}
   {Dashes under title}
   Service Request Template:
       "{Copy-paste ready request text...}"

   Environment Variables:
       {VAR_NAME} = {placeholder-or-value}

2. {NEXT RESOURCE}
   ...

--------------------------------------------------------------------------------
DEPLOYMENT VERIFICATION
--------------------------------------------------------------------------------

After configuration, verify with:

    curl https://{app-url}/api/health

Expected response includes:
    "{component}": {{"status": "healthy"}}

Common Failure Messages:
    {ErrorType}: {description}
        → {Solution}

--------------------------------------------------------------------------------
{OPTIONAL SECTIONS: ARCHITECTURE, AUTHENTICATION MODES, etc.}
--------------------------------------------------------------------------------

Exports:
    {Class1}: {description}
    {Class2}: {description}
"""
```

### Pattern 2: Service Request Template Format

Each Azure resource follows this structure:

```
1. {RESOURCE NAME IN CAPS}
   {Dashes matching length}
   Service Request Template:
       "Create {Resource Type}:
        - Name: {naming-convention}
        - SKU: {recommended-sku}
        - {Key Setting}: {value}
        - {Key Setting}: {value}

        {Additional instructions if needed}"

   Environment Variables:
       {VAR_NAME} = {placeholder}
```

### Pattern 3: Placeholder Conventions

Replace DEV-specific values with these placeholders:

| DEV Value | Placeholder | Usage |
|-----------|-------------|-------|
| `rmhpgflex.postgres...` | `{server-name}.postgres.database.azure.com` | PostgreSQL host |
| `geopgflex` | `{database-name}` | Database name |
| `rmhpgflexadmin` | `{identity-name}` | Managed identity |
| `rmhazuregeo` | `{app-name}-bronze`, `{app-name}-silver` | Storage accounts |
| `rmhazuregeoapi` | `{app-url}` | Function App URL |
| `rmhazure_rg` | `{your-resource-group}` | Resource group |

### Pattern 4: Verification Section

Always include:

```
--------------------------------------------------------------------------------
DEPLOYMENT VERIFICATION
--------------------------------------------------------------------------------

After configuration, verify with:

    curl https://{app-url}/api/health

Expected response includes:
    "{component}": {
        "status": "healthy",
        "{key}": "{value}"
    }

{Optional: Test command}
    curl -X POST https://{app-url}/api/...

Common Failure Messages:
    {ErrorType}: {Brief description}
        → {One-line solution}

    {ErrorType2}: {Brief description}
        → {One-line solution}
```

### Pattern 5: Authentication Modes

For resources supporting multiple auth methods:

```
--------------------------------------------------------------------------------
AUTHENTICATION MODES
--------------------------------------------------------------------------------

1. MANAGED IDENTITY (Production - Recommended)
   - {Benefit 1}
   - {Benefit 2}

   Environment Variables:
       {VAR_NAME} = {value}

2. {ALTERNATIVE} (Development/Troubleshooting Only)
   - {Use case}
   - Never use in production

   Environment Variables:
       {VAR_NAME} = {value}
```

### Pattern 6: Class Docstring Enhancements

For classes with Azure resource dependencies:

```python
class SomeConfig(BaseModel):
    """
    {Brief description}.

    ============================================================================
    {OPTIONAL CONTEXT HEADER IF NEEDED}
    ============================================================================
    {Additional context about when/how to use this class}

    Environment Variables:
        {VAR_NAME}: {Description} (default: {default})
        {VAR_NAME}: {Description} (required)

    Usage:
        from config import get_config
        config = get_config()
        value = config.{path}.{attribute}
    """
```

### Pattern 7: Hardcoded Value Replacement

When finding hardcoded values:

1. **Check if constant exists** in `config/defaults.py`
2. **If not, add it** to appropriate `*Defaults` class
3. **Replace hardcoded value** with constant reference
4. **Update imports** if needed

Example:
```python
# Before
default="rmhazure_rg"

# After (in defaults.py)
class AzureDefaults:
    RESOURCE_GROUP = "your-resource-group-name"

# After (in config file)
from .defaults import AzureDefaults
default=AzureDefaults.RESOURCE_GROUP
```

### Pattern 8: Field Examples

Replace DEV-specific examples with placeholders:

```python
# Before
examples=["rmhpgflex.postgres.database.azure.com"]

# After
examples=["{server-name}.postgres.database.azure.com"]
```

### Pattern 9: File Header with Review Date

**IMPORTANT**: Add or update the file header to track when the docstring review was performed:

```python
# ============================================================================
# CLAUDE CONTEXT - {DESCRIPTIVE_TITLE}
# ============================================================================
# STATUS: {Component type} - {Brief description}
# PURPOSE: {One sentence description}
# LAST_REVIEWED: {DD MMM YYYY}
# REVIEW_STATUS: Check 8 Applied | Checks 1-7 Only | Pending
# ============================================================================
```

For config files with Check 8 applied:
```python
# ============================================================================
# CLAUDE CONTEXT - POSTGRESQL DATABASE CONFIGURATION
# ============================================================================
# STATUS: Configuration - PostgreSQL connection and managed identity
# PURPOSE: Configure database connections for app and business databases
# LAST_REVIEWED: 02 JAN 2026
# REVIEW_STATUS: Check 8 Applied - Full operational deployment guide
# ============================================================================
```

This allows future reviewers (human or Claude) to quickly see:
- When the file was last reviewed
- What level of review was performed
- Whether operational documentation exists

---

## Review Session Log

### Session 1: 02 JAN 2026 - config/ (4 files) - Code Quality Focus

| File | Status | Issues Found | Fixed |
|------|--------|--------------|-------|
| `__init__.py` | [x] | Outdated structure listing (missing 6 files) | ✅ |
| `analytics_config.py` | [~] | None - excellent docstrings | - |
| `app_config.py` | [x] | 2 hardcoded values (`rmhazure_rg`, `silver-cogs`) | ✅ |
| `defaults.py` | [x] | Added `AzureDefaults.RESOURCE_GROUP` | ✅ |

**Fixes applied (Checks 1-6):**
1. `config/__init__.py` - Updated structure listing to include all 13 files
2. `config/defaults.py` - Added `AzureDefaults.RESOURCE_GROUP`
3. `config/app_config.py` - Replaced `"rmhazure_rg"` → `AzureDefaults.RESOURCE_GROUP`
4. `config/app_config.py` - Replaced `"silver-cogs"` → `StorageDefaults.SILVER_COGS`

**Note:** Check 8 (Operational Deployment) not yet applied - need to revisit P0 files with corporate QA lens.

### Session 2: 02 JAN 2026 - Check 8 Example (defaults.py)

Applied Check 8 (Operational Deployment Documentation) to `config/defaults.py` as template:

| Section Added | Content |
|---------------|---------|
| Module docstring | Complete deployment guide with 6 numbered service requests |
| AzureDefaults class | Service request templates for each resource type |
| Verification steps | Health check commands and expected responses |
| Failure messages | Common errors and what they mean |

**Key additions:**
1. **Service Request Templates** - Copy-paste ready for IT tickets
2. **Environment Variable Mapping** - Which var corresponds to which resource
3. **Verification Commands** - `curl` commands to confirm deployment
4. **Failure Diagnosis** - What error messages mean and how to fix

**This serves as the TEMPLATE for all P0/P1 files.**

### Session 3: 02 JAN 2026 - database_config.py (P0)

Applied full 8-check review:

| Check | Status | Action |
|-------|--------|--------|
| 1. Module docstring | [x] | Added full deployment guide (~150 lines) |
| 2. Class docstrings | [~] | Already good |
| 3. Hardcoded values | [x] | Fixed DEV examples: `rmhpgflex`, `geopgflex`, `ddhgeodb` |
| 4. Magic numbers | [~] | Uses DatabaseDefaults |
| 5. Outdated comments | [~] | OK |
| 6. Imports | [~] | OK |
| 7. Env var docs | [~] | Already good |
| 8. Operational docs | [x] | Added service request templates, SQL examples, verification |

**Key additions:**
1. Complete PostgreSQL Flexible Server service request template
2. Schema creation SQL with all required extensions
3. Managed identity database user setup SQL
4. Authentication modes comparison (managed identity vs password)
5. Deployment verification commands
6. Common failure messages with solutions

**Fixes:**
- Removed DEV-specific examples (`rmhpgflex.postgres.database.azure.com` → `{server-name}...`)
- Removed hardcoded `ddhgeodb` default (now requires explicit BUSINESS_DB_NAME)
- Replaced `rmhpgflexadmin` references with `{identity-name}` placeholders

### Session 4: 02 JAN 2026 - storage_config.py + queue_config.py (P0)

Applied Check 8 to both remaining P0 files:

**storage_config.py:**
- Added deployment guide (~120 lines)
- Storage account service request templates (Bronze, Silver, Gold zones)
- Managed identity access configuration
- Container creation guidance
- Deployment scenarios (dev single-account vs prod multi-account)
- Fixed DEV-specific "rmhazuregeo" reference → generic description

**queue_config.py:**
- Added deployment guide (~140 lines)
- Service Bus namespace creation template
- Queue creation with specific settings (TTL, lock duration, max delivery)
- Managed identity access roles (Sender/Receiver)
- Authentication modes (connection string vs managed identity)
- Test job submission command

**All P0 files now have Check 8 operational documentation.**

---

## Root Level Files

| Status | File | Notes |
|--------|------|-------|
| [ ] | `exceptions.py` | |
| [ ] | `function_app.py` | Main entry point |
| [ ] | `util_logger.py` | |

---

## config/ (13 files)

| Status | File | Notes |
|--------|------|-------|
| [x] | `__init__.py` | Fixed: outdated structure listing |
| [~] | `analytics_config.py` | Excellent docstrings, no changes |
| [x] | `app_config.py` | Fixed: 2 hardcoded values |
| [ ] | `app_mode_config.py` | |
| [x] | `database_config.py` | Full Check 8 applied - deployment guide added |
| [x] | `defaults.py` | Added RESOURCE_GROUP constant |
| [ ] | `h3_config.py` | |
| [ ] | `metrics_config.py` | |
| [ ] | `platform_config.py` | |
| [x] | `queue_config.py` | Full Check 8 applied - Service Bus deployment guide |
| [ ] | `raster_config.py` | |
| [x] | `storage_config.py` | Full Check 8 applied - Storage accounts deployment guide |
| [ ] | `vector_config.py` | |

---

## core/ (36 files)

### core/ root

| Status | File | Notes |
|--------|------|-------|
| [ ] | `__init__.py` | |
| [ ] | `core_controller.py` | |
| [ ] | `error_handler.py` | |
| [ ] | `errors.py` | |
| [ ] | `machine.py` | |
| [ ] | `orchestration_manager.py` | |
| [ ] | `state_manager.py` | |
| [ ] | `task_id.py` | |
| [ ] | `utils.py` | |

### core/contracts/

| Status | File | Notes |
|--------|------|-------|
| [ ] | `__init__.py` | |

### core/logic/

| Status | File | Notes |
|--------|------|-------|
| [ ] | `__init__.py` | |
| [ ] | `calculations.py` | |
| [ ] | `transitions.py` | |

### core/models/ (15 files)

| Status | File | Notes |
|--------|------|-------|
| [ ] | `__init__.py` | |
| [ ] | `band_mapping.py` | |
| [ ] | `context.py` | |
| [ ] | `curated.py` | |
| [ ] | `enums.py` | |
| [ ] | `etl.py` | |
| [ ] | `janitor.py` | |
| [ ] | `job.py` | |
| [ ] | `platform.py` | |
| [ ] | `promoted.py` | |
| [ ] | `results.py` | |
| [ ] | `stac.py` | |
| [ ] | `stage.py` | |
| [ ] | `task.py` | |
| [ ] | `unpublish.py` | |

### core/schema/ (9 files)

| Status | File | Notes |
|--------|------|-------|
| [ ] | `__init__.py` | |
| [ ] | `ddl_utils.py` | |
| [ ] | `deployer.py` | |
| [ ] | `geo_table_builder.py` | |
| [ ] | `orchestration.py` | |
| [ ] | `queue.py` | |
| [ ] | `sql_generator.py` | |
| [ ] | `updates.py` | |
| [ ] | `workflow.py` | |

---

## infrastructure/ (31 files)

| Status | File | Notes |
|--------|------|-------|
| [ ] | `__init__.py` | |
| [ ] | `base.py` | |
| [ ] | `blob.py` | |
| [ ] | `curated_repository.py` | |
| [ ] | `data_factory.py` | |
| [ ] | `database_utils.py` | |
| [ ] | `decorators_blob.py` | |
| [ ] | `duckdb_query.py` | |
| [ ] | `duckdb.py` | |
| [ ] | `factory.py` | |
| [ ] | `h3_batch_tracking.py` | |
| [ ] | `h3_repository.py` | |
| [ ] | `h3_schema.py` | |
| [ ] | `h3_source_repository.py` | |
| [ ] | `h3_source_seeds.py` | |
| [ ] | `interface_repository.py` | |
| [ ] | `janitor_repository.py` | |
| [ ] | `job_progress_contexts.py` | |
| [ ] | `job_progress.py` | |
| [ ] | `jobs_tasks.py` | |
| [ ] | `metrics_repository.py` | |
| [ ] | `pgstac_bootstrap.py` | |
| [ ] | `pgstac_repository.py` | |
| [ ] | `platform.py` | |
| [ ] | `postgis.py` | |
| [ ] | `postgresql.py` | |
| [ ] | `promoted_repository.py` | |
| [ ] | `service_bus.py` | |
| [ ] | `validators.py` | |
| [ ] | `vault.py` | |

---

## jobs/ (30 files)

| Status | File | Notes |
|--------|------|-------|
| [ ] | `__init__.py` | |
| [ ] | `base.py` | |
| [ ] | `bootstrap_h3_land_grid_pyramid.py` | |
| [ ] | `container_summary.py` | |
| [ ] | `create_h3_base.py` | |
| [ ] | `curated_update.py` | |
| [ ] | `generate_h3_level4.py` | |
| [ ] | `h3_export_dataset.py` | |
| [ ] | `h3_raster_aggregation.py` | |
| [ ] | `h3_register_dataset.py` | |
| [ ] | `hello_world.py` | |
| [ ] | `ingest_collection.py` | |
| [ ] | `inventory_container_contents.py` | |
| [ ] | `inventory_fathom_container.py` | |
| [ ] | `mixins.py` | |
| [ ] | `process_fathom_merge.py` | |
| [ ] | `process_fathom_stack.py` | |
| [ ] | `process_large_raster_v2.py` | |
| [ ] | `process_raster_collection_v2.py` | |
| [ ] | `process_raster_v2.py` | |
| [ ] | `process_vector.py` | |
| [ ] | `raster_mixin.py` | |
| [ ] | `raster_workflows_base.py` | |
| [ ] | `repair_stac_items.py` | |
| [ ] | `stac_catalog_container.py` | |
| [ ] | `stac_catalog_vectors.py` | |
| [ ] | `unpublish_raster.py` | |
| [ ] | `unpublish_vector.py` | |
| [ ] | `validate_raster_job.py` | |

---

## services/ (47 files)

### services/ root

| Status | File | Notes |
|--------|------|-------|
| [ ] | `__init__.py` | |
| [ ] | `container_analysis.py` | |
| [ ] | `container_inventory.py` | |
| [ ] | `container_summary.py` | |
| [ ] | `delivery_discovery.py` | |
| [ ] | `fathom_container_inventory.py` | |
| [ ] | `fathom_etl.py` | |
| [ ] | `geospatial_inventory.py` | |
| [ ] | `handler_cascade_h3_descendants.py` | |
| [ ] | `handler_create_h3_stac.py` | |
| [ ] | `handler_finalize_h3_pyramid.py` | |
| [ ] | `handler_generate_h3_grid.py` | |
| [ ] | `handler_h3_native_streaming.py` | |
| [ ] | `hello_world.py` | |
| [ ] | `iso3_attribution.py` | |
| [ ] | `janitor_service.py` | |
| [ ] | `pgstac_search_registration.py` | |
| [ ] | `promote_service.py` | |
| [ ] | `raster_cog.py` | |
| [ ] | `raster_mosaicjson.py` | |
| [ ] | `raster_validation.py` | |
| [ ] | `registry.py` | |
| [ ] | `service_hello_world.py` | |
| [ ] | `service_stac_metadata.py` | |
| [ ] | `service_stac_setup.py` | |
| [ ] | `service_stac_vector.py` | |
| [ ] | `stac_catalog.py` | |
| [ ] | `stac_client.py` | |
| [ ] | `stac_collection.py` | |
| [ ] | `stac_metadata_helper.py` | |
| [ ] | `stac_repair_handlers.py` | |
| [ ] | `stac_validation.py` | |
| [ ] | `stac_vector_catalog.py` | |
| [ ] | `task.py` | |
| [ ] | `tiling_extraction.py` | |
| [ ] | `tiling_scheme.py` | |
| [ ] | `titiler_client.py` | |
| [ ] | `titiler_search_service.py` | |
| [ ] | `unpublish_handlers.py` | |
| [ ] | `xarray_reader.py` | |

### services/curated/

| Status | File | Notes |
|--------|------|-------|
| [ ] | `__init__.py` | |
| [ ] | `registry_service.py` | |
| [ ] | `wdpa_handler.py` | |

### services/h3_aggregation/

| Status | File | Notes |
|--------|------|-------|
| [ ] | `__init__.py` | |
| [ ] | `base.py` | |
| [ ] | `handler_export.py` | |
| [ ] | `handler_finalize.py` | |
| [ ] | `handler_inventory.py` | |
| [ ] | `handler_raster_zonal.py` | |
| [ ] | `handler_register.py` | |

### services/ingest/

| Status | File | Notes |
|--------|------|-------|
| [ ] | `__init__.py` | |
| [ ] | `handler_copy.py` | |
| [ ] | `handler_inventory.py` | |
| [ ] | `handler_register.py` | |

### services/vector/

| Status | File | Notes |
|--------|------|-------|
| [ ] | `__init__.py` | |
| [ ] | `converters.py` | |
| [ ] | `helpers.py` | |
| [ ] | `postgis_handler.py` | |
| [ ] | `process_vector_tasks.py` | |

---

## triggers/ (35 files)

### triggers/ root

| Status | File | Notes |
|--------|------|-------|
| [ ] | `__init__.py` | |
| [ ] | `analyze_container.py` | |
| [ ] | `get_blob_metadata.py` | |
| [ ] | `get_job_status.py` | |
| [ ] | `health.py` | |
| [ ] | `http_base.py` | |
| [ ] | `list_container_blobs.py` | |
| [ ] | `list_storage_containers.py` | |
| [ ] | `livez.py` | |
| [ ] | `promote.py` | |
| [ ] | `schema_pydantic_deploy.py` | |
| [ ] | `stac_collections.py` | |
| [ ] | `stac_extract.py` | |
| [ ] | `stac_init.py` | |
| [ ] | `stac_inspect.py` | |
| [ ] | `stac_nuke.py` | |
| [ ] | `stac_setup.py` | |
| [ ] | `stac_vector.py` | |
| [ ] | `submit_job.py` | |
| [ ] | `trigger_platform_status.py` | |
| [ ] | `trigger_platform.py` | |

### triggers/admin/

| Status | File | Notes |
|--------|------|-------|
| [ ] | `__init__.py` | |
| [ ] | `admin_db.py` | |
| [ ] | `admin_servicebus.py` | |
| [ ] | `db_data.py` | |
| [ ] | `db_diagnostics.py` | |
| [ ] | `db_health.py` | |
| [ ] | `db_maintenance.py` | |
| [ ] | `db_queries.py` | |
| [ ] | `db_schemas.py` | |
| [ ] | `db_tables.py` | |
| [ ] | `h3_datasets.py` | |
| [ ] | `h3_debug.py` | |
| [ ] | `servicebus.py` | |
| [ ] | `stac_repair.py` | |

### triggers/curated/

| Status | File | Notes |
|--------|------|-------|
| [ ] | `__init__.py` | |
| [ ] | `admin.py` | |
| [ ] | `scheduler.py` | |

### triggers/janitor/

| Status | File | Notes |
|--------|------|-------|
| [ ] | `__init__.py` | |
| [ ] | `http_triggers.py` | |
| [ ] | `job_health.py` | |
| [ ] | `orphan_detector.py` | |
| [ ] | `task_watchdog.py` | |

---

## API Modules (24 files)

### ogc_features/

| Status | File | Notes |
|--------|------|-------|
| [ ] | `__init__.py` | |
| [ ] | `config.py` | |
| [ ] | `models.py` | |
| [ ] | `repository.py` | |
| [ ] | `service.py` | |
| [ ] | `triggers.py` | |

### ogc_styles/

| Status | File | Notes |
|--------|------|-------|
| [ ] | `__init__.py` | |
| [ ] | `models.py` | |
| [ ] | `repository.py` | |
| [ ] | `service.py` | |
| [ ] | `translator.py` | |
| [ ] | `triggers.py` | |

### raster_api/

| Status | File | Notes |
|--------|------|-------|
| [ ] | `__init__.py` | |
| [ ] | `config.py` | |
| [ ] | `service.py` | |
| [ ] | `triggers.py` | |

### stac_api/

| Status | File | Notes |
|--------|------|-------|
| [ ] | `__init__.py` | |
| [ ] | `config.py` | |
| [ ] | `service.py` | |
| [ ] | `triggers.py` | |

### xarray_api/

| Status | File | Notes |
|--------|------|-------|
| [ ] | `__init__.py` | |
| [ ] | `config.py` | |
| [ ] | `output.py` | |
| [ ] | `service.py` | |
| [ ] | `triggers.py` | |

---

## Viewers (9 files)

### raster_collection_viewer/

| Status | File | Notes |
|--------|------|-------|
| [ ] | `__init__.py` | |
| [ ] | `service.py` | |
| [ ] | `triggers.py` | |

### vector_viewer/

| Status | File | Notes |
|--------|------|-------|
| [ ] | `__init__.py` | |
| [ ] | `service.py` | |
| [ ] | `triggers.py` | |

---

## web_interfaces/ (56 files)

### web_interfaces/ root

| Status | File | Notes |
|--------|------|-------|
| [ ] | `__init__.py` | |
| [ ] | `base.py` | |

### Interface Modules (27 interfaces x 2 files each)

| Status | Interface | Files | Notes |
|--------|-----------|-------|-------|
| [ ] | docs | `__init__.py`, `interface.py` | |
| [ ] | execution | `__init__.py`, `interface.py` | |
| [ ] | gallery | `__init__.py`, `interface.py` | |
| [ ] | h3 | `__init__.py`, `interface.py` | |
| [ ] | h3_sources | `__init__.py`, `interface.py` | |
| [ ] | health | `__init__.py`, `interface.py` | |
| [ ] | home | `__init__.py`, `interface.py` | |
| [ ] | jobs | `__init__.py`, `interface.py` | |
| [ ] | map | `__init__.py`, `interface.py` | |
| [ ] | metrics | `__init__.py`, `interface.py` | |
| [ ] | pipeline | `__init__.py`, `interface.py` | |
| [ ] | platform | `__init__.py`, `interface.py` | |
| [ ] | promote_vector | `__init__.py`, `interface.py` | |
| [ ] | promoted_viewer | `__init__.py`, `interface.py` | |
| [ ] | queues | `__init__.py`, `interface.py` | |
| [ ] | raster_viewer | `__init__.py`, `interface.py` | |
| [ ] | stac | `__init__.py`, `interface.py` | |
| [ ] | stac_map | `__init__.py`, `interface.py` | |
| [ ] | storage | `__init__.py`, `interface.py` | |
| [ ] | submit_raster | `__init__.py`, `interface.py` | |
| [ ] | submit_raster_collection | `__init__.py`, `interface.py` | |
| [ ] | submit_vector | `__init__.py`, `interface.py` | |
| [ ] | swagger | `__init__.py`, `interface.py` | |
| [ ] | tasks | `__init__.py`, `interface.py` | |
| [ ] | vector | `__init__.py`, `interface.py` | |
| [ ] | zarr | `__init__.py`, `interface.py` | |

---

## utils/ (3 files)

| Status | File | Notes |
|--------|------|-------|
| [ ] | `__init__.py` | |
| [ ] | `contract_validator.py` | |
| [ ] | `import_validator.py` | |

---

## scripts/ (4 files)

| Status | File | Notes |
|--------|------|-------|
| [ ] | `copy_era5_subset.py` | |
| [ ] | `copy_gridmet_subset.py` | |
| [ ] | `test_database_stats.py` | |
| [ ] | `validate_config.py` | |

---

## test/ (20 files)

| Status | File | Notes |
|--------|------|-------|
| [ ] | `test_bigint_casting.py` | |
| [ ] | `test_composed_sql_local.py` | |
| [ ] | `test_deploy_local.py` | |
| [ ] | `test_deployment_readiness.py` | |
| [ ] | `test_health_schema.py` | |
| [ ] | `test_local_integration.py` | |
| [ ] | `test_managed_identity.py` | |
| [ ] | `test_minimal.py` | |
| [ ] | `test_mosaicjson_urls_simple.py` | |
| [ ] | `test_mosaicjson_urls.py` | |
| [ ] | `test_phase_0_2_migration.py` | |
| [ ] | `test_raster_create.py` | |
| [ ] | `test_raster_generator.py` | |
| [ ] | `test_repository_basic.py` | |
| [ ] | `test_repository_refactor.py` | |
| [ ] | `test_signature_fix.py` | |
| [ ] | `test_titiler_urls.py` | |
| [ ] | `test_unified_hello.py` | |
| [ ] | `test_unified_sql_gen.py` | |

---

## Summary by Priority

### High Priority (Core Architecture)
- [ ] `config/` - 13 files (likely has hardcoded defaults)
- [ ] `core/` - 36 files (critical business logic)
- [ ] `infrastructure/` - 31 files (database connections, external services)

### Medium Priority (Business Logic)
- [ ] `jobs/` - 30 files (ETL job definitions)
- [ ] `services/` - 47 files (task handlers)
- [ ] `triggers/` - 35 files (API endpoints)

### Lower Priority (UI/Test)
- [ ] `web_interfaces/` - 56 files (HTML generation)
- [ ] `test/` - 20 files
- [ ] API modules - 24 files
- [ ] Viewers - 9 files

---

## Common Hardcoded Values to Find

```python
# Container names
"bronze-raster", "silver-raster", "gold-raster"
"bronze-vector", "silver-vector"
"rmhazuregeobronze", "rmhazuregeosilver"

# Schema names
"app", "geo", "h3", "pgstac"

# URLs
"rmhazuregeoapi", ".azurewebsites.net"
"rmhpgflex.postgres.database.azure.com"

# Queue names
"raster-queue", "vector-queue", "h3-queue"

# Magic numbers
60, 300, 3600 (timeouts)
100, 1000, 10000 (limits)
```

---

## Progress Tracking

| Category | Total | Reviewed | Remaining |
|----------|-------|----------|-----------|
| config/ | 13 | 7 | 6 |
| core/ | 36 | 0 | 36 |
| infrastructure/ | 31 | 0 | 31 |
| jobs/ | 30 | 0 | 30 |
| services/ | 47 | 0 | 47 |
| triggers/ | 35 | 0 | 35 |
| API modules | 24 | 0 | 24 |
| web_interfaces/ | 56 | 0 | 56 |
| utils/ | 3 | 0 | 3 |
| scripts/ | 4 | 0 | 4 |
| test/ | 20 | 0 | 20 |
| Root files | 3 | 0 | 3 |
| **TOTAL** | **302** | **7** | **295** |

---

## Change Log

| Date | Action | Details |
|------|--------|---------|
| 02 JAN 2026 | Created | Initial file inventory |
| 02 JAN 2026 | Session 1 | Reviewed 4 config/ files, developed 7-check systematic process |
| 02 JAN 2026 | Check 8 Added | Added operational deployment documentation checks for corporate QA/PROD |
| 02 JAN 2026 | Session 2 | Applied Check 8 to `config/defaults.py` as template example |
| 02 JAN 2026 | Session 3 | Applied full 8-check review to `config/database_config.py` |
| 02 JAN 2026 | Session 4 | Applied Check 8 to `config/storage_config.py` and `config/queue_config.py` |
