# Environment Portability Audit

**Created**: 02 JAN 2026
**Purpose**: Track hardcoded values that prevent copying codebase to new environments (e.g., QA, staging, production)

---

## Design Principle

The codebase uses a **fail-fast design** where tenant-specific values use INTENTIONALLY INVALID placeholders in `config/defaults.py`. This ensures deployments fail loudly if required environment variables aren't set.

**The problem**: Code OUTSIDE `defaults.py` bypasses these patterns with hardcoded dev environment values.

---

## Findings Summary

| Severity | Count | Description |
|----------|-------|-------------|
| CRITICAL | 3 | Hardcoded URLs - will break immediately |
| HIGH | 7 | Hardcoded fallbacks - should use placeholders |
| MEDIUM | 1 | Schema fallbacks - violates explicit env var requirement |
| OK | ~10 | Documentation only - no runtime impact |

---

## CRITICAL - Will Break in New Environment

These hardcoded values will cause immediate failures in any non-dev deployment.

### 1. Platform Status Trigger URLs

**File**: `triggers/trigger_platform_status.py`

| Line | Current Value | Fix |
|------|---------------|-----|
| 358 | `https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net` | Use `config.etl_app_url` |
| 361 | `https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net` | Use `config.etl_app_url` |
| 363 | `https://rmhazuregeo.z13.web.core.windows.net` | Add `WEB_MAP_URL` env var or config property |

**Context**: Exception handler fallback URLs and web map link.

### 2. Platform Model Storage URL

**File**: `core/models/platform.py`

| Line | Current Value | Fix |
|------|---------------|-----|
| 176 | `https://rmhazuregeo.blob.core.windows.net` | Use `config.storage.bronze.account_name` to build URL |

**Context**: Building blob URLs in platform model.

### 3. OGC Features Managed Identity

**File**: `ogc_features/config.py`

| Line | Current Value | Fix |
|------|---------------|-----|
| 99 | `os.getenv("DB_ADMIN_MANAGED_IDENTITY_NAME", "rmhpgflexadmin")` | Use `AzureDefaults.MANAGED_IDENTITY_NAME` as fallback |
| 127 | `return "rmhpgflexadmin"  # Default` | Use `AzureDefaults.MANAGED_IDENTITY_NAME` |

**Context**: Database managed identity name with dev-specific fallback.

---

## HIGH - Hardcoded Fallbacks

These use hardcoded dev values as fallbacks instead of fail-fast placeholders.

### 4. App Config Resource Group

**File**: `config/app_config.py`

| Line | Current Value | Fix |
|------|---------------|-----|
| 302 | `os.environ.get("ADF_RESOURCE_GROUP", "rmhazure_rg")` | Add `AzureDefaults.RESOURCE_GROUP` placeholder |

**Context**: Azure Data Factory resource group fallback.

### 5. DuckDB Storage Account

**File**: `infrastructure/duckdb.py`

| Line | Current Value | Fix |
|------|---------------|-----|
| 156 | `os.getenv("GOLD_STORAGE_ACCOUNT", "rmhazuregeo")` | Use `StorageDefaults.DEFAULT_ACCOUNT_NAME` |

**Context**: Gold tier storage account for DuckDB queries.

### 6. XArray API Storage Account

**File**: `xarray_api/config.py`

| Line | Current Value | Fix |
|------|---------------|-----|
| 17 | `storage_account: str = "rmhazuregeo"` | Use `StorageDefaults.DEFAULT_ACCOUNT_NAME` |
| 65 | `os.getenv("AZURE_STORAGE_ACCOUNT", "rmhazuregeo")` | Use `StorageDefaults.DEFAULT_ACCOUNT_NAME` |

**Context**: Zarr/NetCDF storage account configuration.

### 7. STAC Model Application Name

**File**: `core/models/stac.py`

| Line | Current Value | Fix |
|------|---------------|-----|
| 162 | `default="rmhazuregeoapi"` | Use `AppModeDefaults.DEFAULT_APP_NAME` |

**Context**: Default `created_by` field in STAC items.

### 8. STAC Metadata Helper Application Name

**File**: `services/stac_metadata_helper.py`

| Line | Current Value | Fix |
|------|---------------|-----|
| 139 | `created_by: str = 'rmhazuregeoapi'` | Use `AppModeDefaults.DEFAULT_APP_NAME` |

**Context**: Default application identifier in STAC metadata.

### 9. DB Maintenance Identity Name

**File**: `triggers/admin/db_maintenance.py`

| Line | Current Value | Fix |
|------|---------------|-----|
| 1865 | `"identity_name": "rmhpgflexadmin"` | Use `AzureDefaults.MANAGED_IDENTITY_NAME` |

**Context**: Example/default identity name in maintenance endpoint.

---

## MEDIUM - Schema Fallbacks

Per 23 DEC 2025 requirement, schema names REQUIRE explicit environment variables. These violate that rule.

### 10. Business Database Schema Fallback

**File**: `config/database_config.py`

| Line | Current Value | Fix |
|------|---------------|-----|
| 503 | `os.environ.get("BUSINESS_DB_SCHEMA", DatabaseDefaults.POSTGIS_SCHEMA)` | Require explicit env var or document as intentional |

**Context**: Business database schema has fallback to `"geo"` via DatabaseDefaults.

---

## OK - Documentation Only

These appear in docstrings, examples, or comments and have no runtime impact:

| File | Lines | Context |
|------|-------|---------|
| `config/database_config.py` | 46 | Pydantic field `examples=` attribute |
| `config/database_config.py` | 133, 167, 173-176, 197, 209 | Docstring examples |
| `config/app_config.py` | 201, 570, 578 | Docstring descriptions |
| `config/app_mode_config.py` | 209 | Docstring example |
| `function_app.py` | 1901, 1939 | Docstring URL examples |
| `vector_viewer/triggers.py` | 68 | Comment example |
| `triggers/list_storage_containers.py` | 14, 17, 20 | Docstring curl examples |

---

## Fix Checklist

- [x] **FIX-1**: `triggers/trigger_platform_status.py` - Replace hardcoded URLs (CRITICAL) - DONE 02 JAN 2026
- [x] **FIX-2**: `core/models/platform.py:176` - Removed dead code (CRITICAL) - DONE 02 JAN 2026
- [ ] **FIX-3**: `ogc_features/config.py` - Use AzureDefaults placeholder (CRITICAL)
- [ ] **FIX-4**: `config/app_config.py:302` - Add resource group to AzureDefaults (HIGH)
- [ ] **FIX-5**: `infrastructure/duckdb.py:156` - Use StorageDefaults placeholder (HIGH)
- [ ] **FIX-6**: `xarray_api/config.py` - Use StorageDefaults placeholder (HIGH)
- [ ] **FIX-7**: `core/models/stac.py:162` - Use AppModeDefaults placeholder (HIGH)
- [ ] **FIX-8**: `services/stac_metadata_helper.py:139` - Use AppModeDefaults placeholder (HIGH)
- [ ] **FIX-9**: `triggers/admin/db_maintenance.py:1865` - Use AzureDefaults (HIGH)
- [ ] **FIX-10**: `config/database_config.py:503` - Review schema fallback (MEDIUM)

---

## Environment Variables Required for Portability

After fixes, these environment variables MUST be set for any deployment:

### Azure Resources (Tenant-Specific)
```bash
# Managed Identity
DB_ADMIN_MANAGED_IDENTITY_NAME=your-managed-identity-name

# Function App URLs
ETL_APP_URL=https://your-etl-app.azurewebsites.net
OGC_STAC_APP_URL=https://your-ogc-stac-app.azurewebsites.net
TITILER_BASE_URL=https://your-titiler-app.azurewebsites.net

# Storage Accounts (zone-specific)
BRONZE_STORAGE_ACCOUNT=your-bronze-account
SILVER_STORAGE_ACCOUNT=your-silver-account
GOLD_STORAGE_ACCOUNT=your-gold-account

# Resource Group (for ADF operations)
ADF_RESOURCE_GROUP=your-resource-group

# Application Identity
APP_NAME=your-function-app-name
```

### Database (Required, No Fallbacks)
```bash
POSTGIS_HOST=your-db.postgres.database.azure.com
POSTGIS_DATABASE=your-database
POSTGIS_SCHEMA=geo
APP_SCHEMA=app
PGSTAC_SCHEMA=pgstac
H3_SCHEMA=h3
```

---

## Validation Script

After deployment, verify no hardcoded dev values remain in runtime:

```bash
# Check for hardcoded account names in logs
az monitor app-insights query --app $APP_INSIGHTS_ID \
  --analytics-query "traces | where message contains 'rmhazuregeo' or message contains 'rmhpgflex' | take 10"
```

---

*Last Updated: 02 JAN 2026*
