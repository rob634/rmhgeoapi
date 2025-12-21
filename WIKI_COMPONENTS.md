# Platform Component Glossary

**Last Updated**: 19 DEC 2025
**Purpose**: Stable reference names for Azure DevOps work items
**Audience**: Development team, Product Owners, DevOps engineers

---

## Why This Glossary Exists

When writing work items, stories, or acceptance criteria, use **logical names** from this document instead of Azure resource names.

**Problem solved**: Azure resources get renamed, environments differ, and not everyone knows that `rmhazuregeosilver` means "processed data storage". This glossary creates a stable abstraction layer.

**Example work item (GOOD)**:
> "Copy approved datasets from **Silver Storage Account** to **External Storage Account** using **Data Factory Instance**"

**Example work item (BAD)**:
> "Copy approved datasets from rmhazuregeosilver to rmhazuregeoexternal using adf-rmhgeo-prod"

The "good" version survives resource renames and works across environments.

---

## Storage

Data flows through tiers: **Bronze → Silver → External**

| Logical Name | Purpose | Access Pattern |
|--------------|---------|----------------|
| **Bronze Storage Account** | Raw uploaded data (input zone) | Write: Users, ETL jobs · Read: Processing handlers |
| **Silver Storage Account** | Processed COGs, validated vectors, Zarr stores | Write: ETL jobs · Read: TiTiler, STAC API, OGC API |
| **External Storage Account** | Public-facing approved datasets | Write: Data Factory · Read: External consumers via CDN |

**Data tier meanings**:
- **Bronze**: "I uploaded it but nothing has verified it yet"
- **Silver**: "ETL processed it, it's valid and cloud-optimized"
- **External**: "Approved for public access, protected by WAF"

---

## Compute

| Logical Name | Purpose | Runtime |
|--------------|---------|---------|
| **ETL Function App** | Job orchestration, HTTP APIs, queue handlers | Azure Functions (Python) |
| **Reader Function App** | Read-only data access APIs (future separation) | Azure Functions (Python) |
| **Long-Running Worker** | Tasks exceeding 30-minute timeout (raster collections, large Zarr) | Docker container |
| **TiTiler Raster Service** | Dynamic tile serving for COGs | Azure Container App |
| **TiTiler Zarr Service** | Dynamic tile serving for Zarr/NetCDF stores | Azure Container App |

**Why two Function Apps?**: Separation enables independent scaling and security boundaries. ETL has write access; Reader has read-only access.

**Why Long-Running Worker?**: Azure Functions have a 10-minute timeout (30 with extension). Large raster mosaics or Zarr aggregations can take hours.

---

## Queues (Service Bus)

| Logical Name | Purpose |
|--------------|---------|
| **Job Queue** | Initial job submission from HTTP endpoints |
| **Vector Task Queue** | Tasks for vector processing handlers |
| **Raster Task Queue** | Tasks for raster processing handlers |
| **Long-Running Task Queue** | Overflow tasks routed to Docker worker |

**Pattern**: HTTP trigger → Job Queue → CoreMachine → Task Queues → Handlers

---

## Database

Single PostgreSQL Flexible Server with logically separated concerns:

| Logical Name | Purpose | Protection Level |
|--------------|---------|------------------|
| **App Database** | Job/task state, curated datasets, H3 grids | Nukeable (can rebuild) |
| **Business Database** | PostGIS `geo` schema, pgSTAC catalog | Protected (user data) |

**Schemas**:
- `app.*` - CoreMachine orchestration tables (jobs, tasks, stages)
- `geo.*` - PostGIS vector feature tables
- `pgstac.*` - STAC catalog (items, collections)
- `h3.*` - Hexagonal grid analytics

| Logical Name | Purpose |
|--------------|---------|
| **App Admin Identity** | Managed identity with DDL privileges (schema creation, table modification) |
| **App Reader Identity** | Managed identity with read-only privileges (API queries) |

---

## External Systems

| Logical Name | Purpose |
|--------------|---------|
| **DDH Application** | Data Hub Dashboard - primary consumer of platform APIs |
| **DDH Service Principal** | Azure AD service principal for DDH authentication |
| **CDN/WAF** | Cloudflare edge protection for External Storage zone |
| **Data Factory Instance** | ADF for approved dataset copy (Silver → External) |

---

## Quick Reference: Common Phrases

| Instead of saying... | Say this... |
|---------------------|-------------|
| "Upload to rmhazuregeobronze" | "Upload to **Bronze Storage Account**" |
| "COGs stored in silver container" | "COGs stored in **Silver Storage Account**" |
| "rmhazuregeoapi function app" | "**ETL Function App**" |
| "geospatial-vector-tasks queue" | "**Vector Task Queue**" |
| "rmhpgflex database" | "**App Database** / **Business Database**" |
| "DDH calls our API" | "**DDH Application** calls **ETL Function App**" |

---

## Environment Mapping (Reference Only)

**This section is informational** - work items should NOT reference these names.

### QA Environment

| Logical Name | Azure Resource |
|--------------|----------------|
| Bronze Storage Account | `rmhazuregeobronze` |
| Silver Storage Account | `rmhazuregeosilver` |
| ETL Function App | `rmhazuregeoapi` |
| App Database | `rmhpgflex` / schema `app` |

### UAT/Prod Environments

Mappings TBD - will be documented in environment-specific runbooks after provisioning.

---

## Related Documentation

| Document | Purpose |
|----------|---------|
| [WIKI_API_STORAGE.md](WIKI_API_STORAGE.md) | Detailed Azure Blob Storage setup and configuration |
| [WIKI_API_SERVICE_BUS.md](WIKI_API_SERVICE_BUS.md) | Service Bus queue configuration |
| [WIKI_API_DATABASE.md](WIKI_API_DATABASE.md) | PostgreSQL setup and schema details |
| [EPICS.md](EPICS.md) | Epic/Feature/Story registry (references these components) |

---

**Usage**: Copy component names directly into ADO work items. The abstraction ensures work items remain meaningful even when Azure resources are renamed or environments change.
