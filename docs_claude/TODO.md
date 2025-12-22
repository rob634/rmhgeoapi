# Working Backlog

**Last Updated**: 21 DEC 2025
**Source of Truth**: [EPICS.md](/EPICS.md) — Epic/Feature/Story definitions live there
**Purpose**: Sprint-level task tracking and delegation

---

## FY26 Priorities (ends 30 JUN 2026)

| Priority | Epic | Name | Status | Next Action |
|:--------:|------|------|--------|-------------|
| 1 | E10 | FATHOM Flood Data Pipeline | 🚧 | Phase 2 retry, scale testing |
| 2 | E2 | Raster Data as API | 🚧 | F2.7: Collection Processing |
| 3 | E3 | DDH Platform Integration | 🚧 | F3.1: Validate Swagger UI |
| 4 | E4 | Data Externalization | 📋 | F4.1: Publishing Workflow |
| 5 | E9 | Zarr/Climate Data as API | 🚧 | F9.2: Virtual Zarr Pipeline |

---

## Current Sprint Focus

### E10: FATHOM Flood Data Pipeline

**Docs**: [FATHOM_ETL.md](./FATHOM_ETL.md)

| Story | Description | Owner | Status |
|-------|-------------|-------|--------|
| F10.1: Phase 1 | Band stacking (8 return periods → 1 COG) | Claude | ✅ CI Complete |
| F10.2: Phase 2 | Spatial merge (N×N tiles → 1 COG) | Claude | ⚠️ 46/47 tasks |
| F10.3: STAC | Register merged COGs to catalog | Claude | 📋 Blocked |
| F10.4: Scale | West Africa / Africa processing | Claude | 📋 |

**Current Issue**: Phase 2 task `n10-n15_w005-w010` failed. Need retry with `force_reprocess=true`.

### E2: Raster Data as API

| Story | Description | Owner | Status |
|-------|-------------|-------|--------|
| F2.7 | Raster Collection Processing (pgstac searches) | Claude | 📋 |
| S2.2.5 | Dynamic TiTiler preview URLs based on band count | Claude | 📋 |

**S2.2.5 Details**: TiTiler fails for >4 band imagery (e.g., WorldView-3 8-band) when default URLs don't specify `bidx` parameters. Need to:
- Detect band count in STAC metadata extraction
- Generate band-appropriate preview URLs (e.g., `&bidx=5&bidx=3&bidx=2` for WV RGB)
- Add WorldView-3 profile to `models/band_mapping.py` ✅ Done 21 DEC 2025

| Story | Description | Owner | Status |
|-------|-------------|-------|--------|
| S2.2.6 | Auto-rescale DEM TiTiler URLs using p2/p98 statistics | Claude | 📋 |

**S2.2.6 Details**: DEMs render grey without proper stretch. Need to:
- Query TiTiler `/cog/statistics` for p2/p98 percentiles during STAC extraction
- Add `&rescale={p2},{p98}&colormap_name=terrain` to DEM preview/viewer URLs
- Store rescale values in STAC item properties for client use

### E3: DDH Platform Integration

| Story | Description | Owner | Status |
|-------|-------------|-------|--------|
| F3.1: API Docs | OpenAPI 3.0 spec + Swagger UI | Claude | ✅ Deployed |
| **F3.1: Validate** | Review Swagger UI, test endpoints | User | 🔍 **Review** |
| F3.2: Identity | DDH service principal setup | DevOps | 📋 |
| F3.3: Envs | QA → UAT → Prod provisioning | DevOps | 📋 |

### E9: Zarr/Climate Data as API

| Story | Description | Owner | Status |
|-------|-------------|-------|--------|
| F9.3: Reader Migration | Copy raster_api/xarray_api to rmhogcstac | Claude | ⬜ Ready |

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
| 21 DEC 2025 | FATHOM Phase 1 complete (CI), Phase 2 46/47 tasks | E10.F10.1-2 |
| 21 DEC 2025 | Fixed dict_row + source_container bugs in fathom_etl.py | E10 |
| 20 DEC 2025 | Swagger UI + OpenAPI spec (19 endpoints, 20 schemas) | E3.F3.1 |
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
