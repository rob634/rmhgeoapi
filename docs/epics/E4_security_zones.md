## Epic E4: Data Externalization & Security Zones 📋

**Business Requirement**: Controlled data movement between security zones via Azure Data Factory
**Status**: 📋 PLANNED
**Last Updated**: 30 DEC 2025

**Strategic Context**:
> E4 handles movement of data between security zones. ADF copies data from the **Silver Zone**
> (internal working storage) to target zones: **External** (public hosting via CDN) or
> **Restricted** (internal but access-controlled). Restricted zone is NOT IN SCOPE currently,
> but the workflow pattern established here will apply to future restricted data scenarios.

```
SILVER ZONE                      TARGET ZONES
(App Working Storage)            ┌─────────────────────────────┐
       │                         │ EXTERNAL (public hosting)   │
       │    Approval +           │  • CDN/WAF fronted          │
       ├───────────────────────▶│  • Public read access       │
       │    ADF Copy             │  • Partner/client delivery  │
       │                         ├─────────────────────────────┤
       │                         │ RESTRICTED (future)         │
       └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ▶│  • Internal but limited     │
             (not in scope)      │  • Role-based access        │
                                 │  • Audit logging            │
                                 └─────────────────────────────┘
```

### Architecture: Python ↔ Data Factory Integration

```
ETL Function App (Python)              Azure Data Factory              Target
┌─────────────────────────┐           ┌─────────────────────┐        ┌─────────────┐
│ AzureDataFactoryRepository │──────▶│ Pipeline Execution  │───────▶│ External    │
│ • trigger_pipeline()     │◀──────│ • Copy Activity     │        │ Storage     │
│ • wait_for_completion()  │ status │ • Linked Services   │        │ or Database │
│ • get_activity_runs()    │        │ • Parameterized     │        │             │
└─────────────────────────┘          └─────────────────────┘        └─────────────┘
        Python side                        ADF GUI side                 Infra side
     (Geospatial owns)                  (DevOps owns)               (DevOps owns)
```

**Python Status**: ✅ `AzureDataFactoryRepository` built (`infrastructure/data_factory.py`)

---

### Feature F4.1: Publishing Workflow 📋 PLANNED

**Owner**: Geospatial Team
**Deliverable**: Approval queue, audit log, status APIs

| Story | Status | Acceptance Criteria |
|-------|--------|---------------------|
| S4.1.1 | ⬜ | Design publish schema (`app.publish_queue`, `app.publish_audit_log`) |
| S4.1.2 | ⬜ | Create publishing repository |
| S4.1.3 | ⬜ | Submit for review endpoint |
| S4.1.4 | ⬜ | Approve/Reject endpoints |
| S4.1.5 | ⬜ | Status check endpoint |
| S4.1.6 | ⬜ | Audit log queries |

---

### Feature F4.2: ADF Python Integration 🚧 PARTIAL

**Owner**: Geospatial Team
**Deliverable**: Python code to trigger and monitor ADF pipelines
**Depends on**: F4.4 (ADF infrastructure must exist first)

| Story | Status | Description | Acceptance Criteria |
|-------|--------|-------------|---------------------|
| S4.2.1 | ✅ | Create `AzureDataFactoryRepository` | Repository can trigger, poll, wait for pipelines |
| S4.2.2 | ✅ | Add ADF config to `app_config.py` | `adf_subscription_id`, `adf_factory_name`, `adf_resource_group` |
| S4.2.3 | ⬜ | Integrate approve endpoint with ADF trigger | `/api/publish/approve` triggers ADF pipeline |
| S4.2.4 | ⬜ | Add ADF status polling to audit log | Audit log updated with copy status |
| S4.2.5 | ⬜ | Add ADF health check to `/api/health` | Health endpoint shows ADF connectivity |
| S4.2.6 | ⬜ | Create `/api/adf/pipelines` listing endpoint | List available pipelines for debugging |
| S4.2.7 | ⬜ | Create `/api/adf/status/{run_id}` endpoint | Check pipeline run status |

**Key Files**: `infrastructure/data_factory.py`, `infrastructure/interface_repository.py`

### F4.2 Python Usage Pattern

```python
# Triggered from approve endpoint after approval workflow completes
from infrastructure import RepositoryFactory

adf_repo = RepositoryFactory.create_data_factory_repository()

# Trigger the pipeline
result = adf_repo.trigger_pipeline(
    pipeline_name="CopyBlobToExternal",
    parameters={
        "source_container": "silver-cogs",
        "source_blob": "rasters/dataset-123/file.tif",
        "destination_container": "public",
        "destination_blob": "rasters/dataset-123/file.tif"
    },
    reference_name=job_id  # For correlation in logs
)

# Optionally wait for completion (or poll asynchronously)
final = adf_repo.wait_for_pipeline_completion(result['run_id'])
# Returns: {'status': 'Succeeded', 'duration_ms': 45000, ...}
```

---

### Feature F4.3: External Delivery Infrastructure 🚧 PARTIAL

**Owner**: DevOps (infrastructure)
**Deliverable**: External storage, database, CDN, and identity configuration

**Current State**: Storage and database are **provisioned** but need validation and configuration.

#### Phase 1: Storage Setup

| Story | Status | Description | Owner | Acceptance Criteria |
|-------|--------|-------------|-------|---------------------|
| S4.3.1 | ✅ | Create **External Storage Account** | DevOps | Storage account exists |
| S4.3.2 | ⬜ | Validate storage access | DevOps | Confirm connectivity, list containers |
| S4.3.3 | ⬜ | Configure storage RBAC | DevOps | Required identities have appropriate roles |
| S4.3.4 | ⬜ | Configure storage CORS | DevOps | CORS allows reads from approved domains |

#### Phase 2: Database Setup

| Story | Status | Description | Owner | Acceptance Criteria |
|-------|--------|-------------|-------|---------------------|
| S4.3.5 | ✅ | Create **External PostgreSQL** | DevOps | Database server exists |
| S4.3.6 | ⬜ | Validate database connectivity | DevOps | Can connect from approved networks |
| S4.3.7 | ⬜ | Install PostGIS extension | DevOps | **Service Request Required** — PostGIS enabled on external DB |
| S4.3.8 | ⬜ | Create external schemas | Geospatial | `geo`, `app`, `pgstac` schemas created |
| S4.3.9 | ⬜ | Configure database RBAC | DevOps | Required identities have appropriate roles |

#### Phase 3: Identity Setup

| Story | Status | Description | Owner | Acceptance Criteria |
|-------|--------|-------------|-------|---------------------|
| S4.3.10 | ⬜ | Create **External Reader Identity** | DevOps | User-assigned managed identity for external read access |
| S4.3.11 | ⬜ | Grant External Reader → External Storage | DevOps | `Storage Blob Data Reader` on external storage |
| S4.3.12 | ⬜ | Grant External Reader → External Database | DevOps | Read-only access to external PostgreSQL |
| S4.3.13 | ⬜ | Document identity separation | DevOps | Internal vs External reader identity matrix |

### F4.3 Identity Separation

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        INTERNAL ZONE                                     │
│  ┌──────────────────────┐         ┌──────────────────────────────────┐ │
│  │ Internal Reader ID   │────────▶│ Bronze/Silver Storage            │ │
│  │ (existing)           │         │ Internal PostgreSQL              │ │
│  └──────────────────────┘         └──────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                        EXTERNAL ZONE                                     │
│  ┌──────────────────────┐         ┌──────────────────────────────────┐ │
│  │ External Reader ID   │────────▶│ External Storage                 │ │
│  │ (NEW - S4.3.10)      │         │ External PostgreSQL              │ │
│  └──────────────────────┘         └──────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘

Principle: Separate identities for internal vs external access
```

#### Phase 4: CDN/WAF Setup

| Story | Status | Description | Owner | Acceptance Criteria |
|-------|--------|-------------|-------|---------------------|
| S4.3.14 | ⬜ | Create Cloudflare zone | DevOps | Zone exists for external data domain |
| S4.3.15 | ⬜ | Configure **CDN/WAF** caching rules | DevOps | COGs and vectors cached at edge |
| S4.3.16 | ⬜ | Configure **CDN/WAF** security rules | DevOps | Rate limiting, bot protection enabled |
| S4.3.17 | ⬜ | Configure custom domain DNS | DevOps | CNAME points to Cloudflare |
| S4.3.18 | ⬜ | Validate end-to-end access | DevOps | Public URL serves data through CDN |

### F4.3 Cloudflare Configuration

**Caching Rules**:
| Path Pattern | Cache TTL | Notes |
|--------------|-----------|-------|
| `*.tif`, `*.tiff` | 7 days | COG files rarely change |
| `*.geojson` | 1 day | Vector exports |
| `*.parquet` | 7 days | Analytics exports |
| `*/metadata.json` | 1 hour | STAC-like metadata |

**Security Rules**:
| Rule | Setting | Rationale |
|------|---------|-----------|
| Rate Limiting | 1000 req/min per IP | Prevent abuse |
| Bot Protection | Challenge suspicious | Block scrapers |
| Hotlink Protection | Enabled | Prevent bandwidth theft |
| Browser Integrity Check | Enabled | Block headless browsers |

### F4.3 Service Requests Required

| Item | Request Type | Notes |
|------|--------------|-------|
| **PostGIS on External DB** | Service Request | Azure Flexible Server requires support ticket for extensions |

---

### Feature F4.4: ADF Infrastructure & Pipelines 📋 PLANNED

**Owner**: DevOps (100% Azure Portal / CLI / ARM work — no Python)
**Deliverable**: Functional ADF instance with copy pipelines
**Skills Needed**: Azure Portal, Data Factory GUI, ARM templates, Azure RBAC

> **For DevOps teammates**: This feature is entirely Azure infrastructure work.
> No Python or geospatial knowledge required. Standard Azure Data Factory patterns.

#### Phase 1: ADF Instance Setup

| Story | Status | Description | Acceptance Criteria |
|-------|--------|-------------|---------------------|
| S4.4.1 | ⬜ | Create Data Factory instance | `az datafactory create --name rmhazureadf --resource-group rmhazure_rg` succeeds |
| S4.4.2 | ⬜ | Enable system-assigned managed identity | ADF has managed identity in Azure AD |
| S4.4.3 | ⬜ | Grant ADF read access to Silver Storage | `Storage Blob Data Reader` role on `rmhstorage123` |
| S4.4.4 | ⬜ | Grant ADF write access to External Storage | `Storage Blob Data Contributor` role on external account |
| S4.4.5 | ⬜ | Document ADF resource names | Add to environment config template |

#### Phase 2: Linked Services (Connections)

| Story | Status | Description | Acceptance Criteria |
|-------|--------|-------------|---------------------|
| S4.4.6 | ⬜ | Create Silver Storage linked service | ADF can connect to Silver using managed identity |
| S4.4.7 | ⬜ | Create External Storage linked service | ADF can connect to External using managed identity |
| S4.4.8 | ⬜ | Test linked service connections | "Test connection" succeeds in ADF UI |

#### Phase 3: Pipeline Development (GUI)

| Story | Status | Description | Acceptance Criteria |
|-------|--------|-------------|---------------------|
| S4.4.9 | ⬜ | Create `CopyBlobToExternal` pipeline | Pipeline exists in ADF with Copy activity |
| S4.4.10 | ⬜ | Add pipeline parameters | Accepts `source_container`, `source_blob`, `destination_container`, `destination_blob` |
| S4.4.11 | ⬜ | Configure Copy activity source | Uses Silver linked service + parameterized path |
| S4.4.12 | ⬜ | Configure Copy activity sink | Uses External linked service + parameterized path |
| S4.4.13 | ⬜ | Add logging/audit activity (optional) | Pipeline logs execution metadata |

#### Phase 4: Testing & Validation

| Story | Status | Description | Acceptance Criteria |
|-------|--------|-------------|---------------------|
| S4.4.14 | ⬜ | Manual pipeline test (Debug) | Run in ADF Debug mode with test parameters |
| S4.4.15 | ⬜ | Trigger test from Azure CLI | `az datafactory pipeline create-run` succeeds |
| S4.4.16 | ⬜ | Monitor run in ADF UI | Can see run status, duration, rows copied |
| S4.4.17 | ⬜ | Verify blob in External Storage | Copied file exists and is identical to source |

#### Phase 5: Function App Configuration

| Story | Status | Description | Acceptance Criteria |
|-------|--------|-------------|---------------------|
| S4.4.18 | ⬜ | Set `ADF_SUBSCRIPTION_ID` in Function App | Environment variable configured |
| S4.4.19 | ⬜ | Set `ADF_FACTORY_NAME` in Function App | Environment variable configured |
| S4.4.20 | ⬜ | Grant Function App identity access to ADF | Function App can trigger pipelines |
| S4.4.21 | ⬜ | End-to-end Python→ADF test | `/api/adf/pipelines` returns list successfully |

### F4.4 Pipeline Parameters Schema

```json
{
  "source_container": "silver-cogs",
  "source_blob": "rasters/dataset-123/file.tif",
  "destination_container": "public",
  "destination_blob": "rasters/dataset-123/file.tif"
}
```

### F4.4 Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│                     Azure Data Factory                                │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │  Pipeline: CopyBlobToExternal                                    │ │
│  │  ┌─────────────┐    ┌────────────────┐    ┌─────────────────┐  │ │
│  │  │ Parameters  │───▶│ Copy Activity  │───▶│ (Optional)      │  │ │
│  │  │ source_*    │    │ Binary copy    │    │ Logging/Audit   │  │ │
│  │  │ dest_*      │    │ No transform   │    │ Activity        │  │ │
│  │  └─────────────┘    └───────┬────────┘    └─────────────────┘  │ │
│  └─────────────────────────────┼─────────────────────────────────────┘ │
│                                │                                      │
│  ┌─────────────────────────────┼─────────────────────────────────────┐ │
│  │  Linked Services            │                                     │ │
│  │  ┌──────────────────┐       │       ┌──────────────────────────┐ │ │
│  │  │ SilverStorage    │───────┴──────▶│ ExternalStorage          │ │ │
│  │  │ (Managed ID)     │  Binary copy  │ (Managed ID)             │ │ │
│  │  │ Blob Data Reader │               │ Blob Data Contributor    │ │ │
│  │  └──────────────────┘               └──────────────────────────┘ │ │
│  └───────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

### F4.4 Azure CLI Quick Reference (for DevOps)

```bash
# Phase 1: Create ADF
az datafactory create \
  --name rmhazureadf \
  --resource-group rmhazure_rg \
  --location eastus

# Enable managed identity (usually automatic with create)
az datafactory show --name rmhazureadf --resource-group rmhazure_rg \
  --query identity

# Phase 1: Grant storage access
ADF_PRINCIPAL_ID=$(az datafactory show --name rmhazureadf \
  --resource-group rmhazure_rg --query identity.principalId -o tsv)

# Reader on Silver
az role assignment create \
  --assignee $ADF_PRINCIPAL_ID \
  --role "Storage Blob Data Reader" \
  --scope /subscriptions/{sub}/resourceGroups/rmhazure_rg/providers/Microsoft.Storage/storageAccounts/rmhstorage123

# Contributor on External
az role assignment create \
  --assignee $ADF_PRINCIPAL_ID \
  --role "Storage Blob Data Contributor" \
  --scope /subscriptions/{sub}/resourceGroups/rmhazure_rg/providers/Microsoft.Storage/storageAccounts/{external-account}

# Phase 5: Set Function App env vars
az functionapp config appsettings set \
  --name rmhazuregeoapi \
  --resource-group rmhazure_rg \
  --settings ADF_SUBSCRIPTION_ID={subscription-id} ADF_FACTORY_NAME=rmhazureadf
```

---

### Feature F4.5: Database-to-Database Pipelines 🔵 BACKLOG

**Owner**: DevOps (ADF) + Geospatial Team (triggers)
**Deliverable**: ADF pipelines for database copy operations
**Status**: Deferred — implement when database promotion workflow is needed

> **Use Case**: Copy staging tables to production, or archive data between databases.
> Similar pattern to blob copy, but uses Azure Database linked services.

| Story | Status | Description |
|-------|--------|-------------|
| S4.5.1 | 🔵 | Create PostgreSQL linked service | ADF connects to Business Database |
| S4.5.2 | 🔵 | Create `CopyTableToProduction` pipeline | Parameterized table copy |
| S4.5.3 | 🔵 | Add database triggers to Python repo | Same pattern as blob triggers |

---

### E4 Dependency Summary

```
F4.4: ADF Infrastructure ──────────────▶ F4.2: Python Integration
        (DevOps)                              (Geospatial)
            │                                      │
            ▼                                      ▼
F4.3: External Storage ─────────────────▶ F4.1: Publishing Workflow
        (DevOps)                              (Geospatial)
                                                   │
                                                   ▼
                                          End-to-End Testing
```

**Critical Path**: F4.4 → F4.2 → F4.1 → Integration Testing

---

---

