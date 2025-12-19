# Working Backlog

**Last Updated**: 19 DEC 2025
**Source of Truth**: [EPICS.md](/EPICS.md) — Epic/Feature/Story definitions live there
**Purpose**: Sprint-level task tracking and delegation

---

## FY26 Priorities (ends 30 JUN 2026)

| Priority | Epic | Name | Status | Next Action |
|:--------:|------|------|--------|-------------|
| 1 | E2 | Raster Data as API | 🚧 | F2.7: Collection Processing |
| 2 | E9 | DDH Platform Integration | 📋 | F9.1: API Documentation |
| 3 | E7 | Data Externalization | 📋 | F7.1: Publishing Workflow |
| 4 | E6 | Platform Observability | 🚧 | F6.3: Verbose Validation |
| 5 | E3 | Zarr/Climate Data as API | 🚧 | F3.2: Virtual Zarr Pipeline |

---

## Current Sprint Focus

### E2: Raster Data as API

| Story | Description | Owner | Status |
|-------|-------------|-------|--------|
| F2.7 | Raster Collection Processing (pgstac searches) | Claude | 📋 |

### E9: DDH Platform Integration

| Story | Description | Owner | Status |
|-------|-------------|-------|--------|
| F9.1: API Docs | OpenAPI 3.0 spec generation | Claude | 📋 |
| F9.2: Identity | DDH service principal setup | DevOps | 📋 |
| F9.3: Envs | QA → UAT → Prod provisioning | DevOps | 📋 |

### E3: Zarr/Climate Data as API

| Story | Description | Owner | Status |
|-------|-------------|-------|--------|
| F3.3: Reader Migration | Copy raster_api/xarray_api to rmhogcstac | Claude | ⬜ Ready |

---

## DevOps / Non-Geospatial Tasks

Tasks suitable for a colleague with Azure/Python/pipeline expertise but without geospatial domain knowledge.

### Ready Now (No Geospatial Knowledge Required)

| Task | Epic | Description | Skills Needed |
|------|------|-------------|---------------|
| **S9.2.2**: Create DDH service principal | E9 | Azure AD service principal for QA | Azure AD, IAM |
| **S9.2.3**: Grant blob read access | E9 | Assign Storage Blob Data Reader | Azure RBAC |
| **S9.2.4**: Grant blob write access | E9 | Assign Storage Blob Data Contributor | Azure RBAC |
| **S9.3.2**: Document QA config | E9 | Export current config for replication | Documentation |
| **EN6.1**: Docker image | EN6 | Create image with GDAL/rasterio/xarray | Docker, Python |
| **EN6.2**: Container deployment | EN6 | Azure Container App or Web App | Azure, DevOps |
| **EN6.3**: Service Bus queue | EN6 | Create `long-running-raster-tasks` queue | Azure Service Bus |
| **EN6.4**: Queue listener | EN6 | Implement in Docker worker | Python, Service Bus SDK |
| **F7.2.1**: Create ADF instance | E7 | `az datafactory create` in rmhazure_rg | Azure Data Factory |
| **F7.3.1**: External storage account | E7 | New storage for public data | Azure Storage |
| **F7.3.2**: Cloudflare WAF rules | E7 | Rate limiting, geo-blocking | Cloudflare |

### Ready After Dependencies

| Task | Epic | Depends On | Description |
|------|------|------------|-------------|
| S9.3.3-6: UAT provisioning | E9 | S9.3.2 | Replicate QA setup to UAT |
| EN6.5: Routing logic | EN6 | EN6.1-4 | Dispatch oversized jobs to Docker worker |
| F7.2.3: Blob-to-blob copy | E7 | F7.2.1 | ADF copy activity |
| F7.2.4: Approve trigger | E7 | F7.1 | Trigger ADF from approval endpoint |

---

## Recently Completed

| Date | Item | Epic |
|------|------|------|
| 18 DEC 2025 | OGC API Styles module | E5.F5.1 |
| 18 DEC 2025 | Service Layer API Phase 4 | E2.F2.5 |
| 12 DEC 2025 | Unpublish workflows | E1.F1.4, E2.F2.4 |
| 11 DEC 2025 | Service Bus queue standardization | EN3 |
| 07 DEC 2025 | Container inventory consolidation | E6 |
| DEC 2025 | PgSTAC Repository Consolidation | EN (completed) |

---

## Quick Links

| Document | Purpose |
|----------|---------|
| [EPICS.md](/EPICS.md) | Master Epic/Feature/Story definitions |
| [HISTORY.md](./HISTORY.md) | Full completion log |
| [READER_MIGRATION_PLAN.md](/READER_MIGRATION_PLAN.md) | F3.3 implementation guide |
| [ARCHITECTURE_REFERENCE.md](./ARCHITECTURE_REFERENCE.md) | Technical patterns |

---

**Workflow**:
1. Pick task from "Current Sprint Focus" or "DevOps Tasks"
2. Update status here as work progresses
3. Reference EPICS.md for acceptance criteria
4. Log completion in HISTORY.md
