# Working Backlog

**Last Updated**: 24 JAN 2026
**Source of Truth**: [docs/epics/README.md](/docs/epics/README.md) - Epic/Feature/Story definitions
**Purpose**: Sprint-level task tracking and delegation (INDEX format)

---

## Quick Navigation

| Document | Purpose |
|----------|---------|
| [COMPLETED_JAN2026.md](./COMPLETED_JAN2026.md) | Completed features (Jan 2026) |
| [COREMACHINE_GAPS.md](./COREMACHINE_GAPS.md) | CoreMachine gap analysis & job_events |
| [APPROVAL_WORKFLOW.md](./APPROVAL_WORKFLOW.md) | F4.AP approval system details |
| [RASTER_METADATA.md](./RASTER_METADATA.md) | F7.9 RasterMetadata architecture |
| [CLASSIFICATION_ENFORCEMENT.md](./CLASSIFICATION_ENFORCEMENT.md) | E4 access_level enforcement |
| [DOCKER_INTEGRATION.md](./DOCKER_INTEGRATION.md) | F7.18 framework, F7.15 HTTP-trigger |
| [/UI_MIGRATION.md](/UI_MIGRATION.md) | UI migration to Jinja2/Docker |
| [HISTORY.md](./HISTORY.md) | Completed work log |

---

## Testing Needed

- [ ] **Test Approval Workflow** - Submit job, verify approval record created, approve via API
- [ ] **Test Artifact/Revision Workflow** - Submit with same DDH identifiers, verify revision increments
- [ ] **Test External Service Registry** - `/api/jobs/services/register`, list, health check

---

## Active Work

### CoreMachine Gap Analysis (E7)
**Status**: GAPS FIXED - Ready for events table
**Details**: [COREMACHINE_GAPS.md](./COREMACHINE_GAPS.md)

| Story | Status |
|-------|--------|
| GAP-3: Check mark_job_failed return | Done |
| GAP-4: Handle task_record None | Done |
| GAP-7: Checkpoint for callback failure | Done |
| GAP-2: Stage advancement checkpoint | Done |
| **Story 5: Create app.job_events table** | PENDING |
| **Story 6: Execution Timeline UI** | PENDING |

---

### UI Migration to Docker/Jinja2
**Status**: Phases 1-3 COMPLETE
**Details**: [/UI_MIGRATION.md](/UI_MIGRATION.md)

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 1 | Foundation (base.html, static files) | Done |
| Phase 2 | Health Dashboard | Done |
| Phase 3 | Unified Collection Browser | Done |
| Phases 4-8 | Remaining interfaces | Pending review |

---

### Dataset Approval System (F4.AP)
**Status**: Phase 1 COMPLETE, Phase 2 IN PROGRESS
**Details**: [APPROVAL_WORKFLOW.md](./APPROVAL_WORKFLOW.md)

| Story | Status |
|-------|--------|
| Core infrastructure (models, repo, service) | Done |
| HTTP endpoints (`/api/approvals/*`) | Done |
| Job completion hook | Done (22 JAN) |
| Viewer UI buttons | Pending |
| ADF integration for public data | Pending |

---

### RasterMetadata + STAC Self-Healing (F7.9 + F7.11)
**Status**: Phase 1 COMPLETE, Phase 2 IN PROGRESS
**Details**: [RASTER_METADATA.md](./RASTER_METADATA.md)
**Priority**: CRITICAL - Raster is primary STAC use case

| Story | Status |
|-------|--------|
| RasterMetadata class + DDL | Done |
| RasterMetadataRepository | Done |
| Wire to extract_stac_metadata | Done |
| Enable raster rebuild | Done |
| Test: process_raster_v2 populates cog_metadata | NEXT |

---

### Docker Orchestration Framework (F7.18)
**Status**: Phases 1-4 COMPLETE
**Details**: [DOCKER_INTEGRATION.md](./DOCKER_INTEGRATION.md)

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 1 | Connection Pool Manager | Done |
| Phase 2 | Checkpoint Integration | Done |
| Phase 3 | Docker Task Context | Done |
| Phase 4 | Graceful Shutdown | Done |
| Phase 5 | H3 Bootstrap Docker | Pending |
| Phase 6 | Migrate process_raster_docker | Done |
| Phase 7 | Documentation | Pending |

---

### Classification Enforcement (E4)
**Status**: Planned
**Details**: [CLASSIFICATION_ENFORCEMENT.md](./CLASSIFICATION_ENFORCEMENT.md)

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 1 | Enforce at Platform Level | Pending |
| Phase 2 | Fail-Fast in Pipeline Tasks | Pending |
| Phase 3 | ADF Integration Testing | Pending |

---

### API Documentation (F12.8 + F12.9)
**Status**: OpenAPI infrastructure COMPLETE

| Deliverable | Status |
|-------------|--------|
| `/api/interface/swagger` | Done |
| `/api/interface/redoc` | Done |
| `/api/openapi.json` | Done |
| TiTiler consumer docs handoff | Done |

---

## FY26 Priorities (ends 30 JUN 2026)

| Priority | Epic | Feature | Status |
|:--------:|------|---------|--------|
| **1** | E7→E2 | RasterMetadata + STAC Self-Healing | CRITICAL |
| **2** | E8 | H3 Analytics (Rwanda) | H3 bootstrap running |
| 3 | E8 | Building Flood Exposure | Pending |
| 4 | E9 | Pre-prepared Raster Ingest | Pending |
| 5 | E2 | Raster Data as API | In Progress |
| 6 | E3 | DDH Platform Integration | In Progress |

**Focus**: Rwanda as test region for all analytics pipelines before scaling.

---

## Current Sprint Focus

### H3 Analytics on Rwanda (E8)
**Goal**: H3 aggregation of FATHOM flood data for Rwanda
**Dependency**: F9.1 FATHOM merged COGs exist in silver-fathom

| Story | Status |
|-------|--------|
| S8.13.1 | Seed Rwanda H3 cells (Stage 3 timeout) |
| S8.13.1a | Fix H3 finalize timeout (pg_cron) | Done |
| S8.13.1b | Enable pg_cron extension | Pending |
| S8.13.1c | Run pg_cron_setup.sql | Pending |
| S8.13.1d | Re-run H3 bootstrap | Pending |
| S8.13.2-5 | Add FATHOM to source_catalog, run aggregation | Pending |

See [TABLE_MAINTENANCE.md](./TABLE_MAINTENANCE.md) for pg_cron setup.

---

### Building Flood Exposure Pipeline (E8)
**Goal**: Calculate % of buildings in flood risk areas, aggregated to H3 level 7
**Dependency**: F8.13 (H3 cells for Rwanda), F9.1 FATHOM COGs
**Data Source**: Microsoft Building Footprints

| Story | Description | Status |
|-------|-------------|--------|
| S8.7.1 | Download MS Building Footprints | Pending |
| S8.7.2 | Create `buildings` schema | Pending |
| S8.7.3 | Create job definition (4-stage) | Pending |
| S8.7.4-7 | Stage handlers | Pending |
| S8.7.8 | Rwanda + fluvial-defended-2020 test | Pending |
| S8.7.9 | Expand to all FATHOM scenarios | Pending |

---

### Add Rasters to Existing Collections (F2.10)
**Status**: Core implementation COMPLETE, Platform wiring pending

| Story | Status |
|-------|--------|
| Add `collection_must_exist` to handlers | Done |
| Add to job parameters_schema | Done |
| Create Platform endpoint | Pending |
| Tests | Pending |

---

## Epic Status Summary

### E2: Raster Data as API

| Feature | Status |
|---------|--------|
| F2.7: Collection Processing | In Progress |
| F2.9: STAC-Integrated Viewer | Done |
| F2.10: Add to Existing Collections | Core done |

### E7: Pipeline Infrastructure

| Feature | Status |
|---------|--------|
| F7.8: VectorMetadata | Done |
| F7.9: RasterMetadata | In Progress |
| F7.10: Metadata Consistency Timer | Done |
| F7.11: STAC Self-Healing | In Progress |
| F7.13: Docker Worker | Done |
| F7.16: db_maintenance.py Split | Done |
| F7.17: Job Resubmit + Features | Done |
| F7.18: Docker Framework | Done (Phases 1-4) |

### E8: GeoAnalytics Pipeline

| Feature | Status |
|---------|--------|
| F8.1-F8.3: Grid infrastructure | Done |
| F8.8: Source Catalog | Done |
| F8.9: H3 Export Pipeline | Done |
| F8.13: Rwanda H3 Aggregation | In Progress |
| F8.7: Building Exposure | Pending |

### E9: Large Data Hosting

| Feature | Status |
|---------|--------|
| F9.1: FATHOM ETL | Done (Rwanda) |
| F9.5: xarray Service | Done |
| F9.6: TiTiler Services | In Progress |
| F9.8: Pre-prepared Ingest | Pending |

### E12: Interface Modernization

| Feature | Status |
|---------|--------|
| F12.1-F12.3: Cleanup, HTMX, Migration | Done |
| F12.3.1: DRY Consolidation | Done |
| SP12.9: NiceGUI Evaluation | Done - Not Pursuing |
| F12.4-F12.8: Remaining interfaces | Pending |

---

## Reference Data Pipelines (Low Priority)

| Feature | Data Source | Status |
|---------|-------------|--------|
| F7.2: IBAT (WDPA, KBAs) | IBAT API | Partial |
| F7.6: ACLED Conflict Data | ACLED API | Pending |
| F7.7: Static Reference (Admin0/1) | Natural Earth | Pending |

---

## DevOps Tasks (No Geospatial Knowledge Required)

| Task | Description | Skills |
|------|-------------|--------|
| S9.2.2 | Create DDH service principal | Azure AD |
| S9.2.3 | Grant blob read access | Azure RBAC |
| EN6.1 | Docker image with GDAL | Docker |
| EN6.2 | Container deployment | Azure DevOps |
| F7.2.1 | Create ADF instance | Azure Data Factory |

---

## Docker Worker Remaining Backlog

| Story | Status |
|-------|--------|
| S7.13.13: Test checkpoint/resume after crash | Pending |
| S7.13.14: Add `process_vector_docker` job | Pending |

---

## Recently Completed

| Date | Item |
|------|------|
| 23 JAN 2026 | UI Migration Phases 1-3 |
| 22 JAN 2026 | Explicit Approval Record Creation |
| 22 JAN 2026 | Infrastructure as Code DRY Cleanup |
| 21 JAN 2026 | Consolidate Status/Unpublish Endpoints |
| 21 JAN 2026 | Force Reprocess via overwrite |
| 21 JAN 2026 | Docker AAD Auth Fix |
| 21 JAN 2026 | Platform Default to Docker |
| 12 JAN 2026 | Job Resubmit Endpoint |
| 12 JAN 2026 | db_maintenance.py Split |

*For full details, see [COMPLETED_JAN2026.md](./COMPLETED_JAN2026.md) and [HISTORY.md](./HISTORY.md)*

---

## Quick Links

| Document | Purpose |
|----------|---------|
| [FATHOM_ETL.md](./FATHOM_ETL.md) | FATHOM flood data pipeline |
| [H3_REVIEW.md](./H3_REVIEW.md) | H3 aggregation implementation |
| [TABLE_MAINTENANCE.md](./TABLE_MAINTENANCE.md) | pg_cron + autovacuum setup |
| [ARCHITECTURE_REFERENCE.md](./ARCHITECTURE_REFERENCE.md) | Technical patterns |
| [docs/epics/README.md](/docs/epics/README.md) | Master Epic/Feature/Story definitions |

---

## Workflow

1. ~~Complete Rwanda FATHOM pipeline (Priority 1)~~ DONE
2. Run H3 aggregation on FATHOM outputs (Priority 2) - H3 bootstrap running
3. Building flood exposure pipeline (Priority 3)
4. Generalize to Pipeline Builder (Future)
