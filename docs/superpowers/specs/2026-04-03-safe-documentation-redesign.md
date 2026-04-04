# SAFe Documentation Redesign — Design Spec

**Date**: 03 APR 2026
**Author**: Robert Harrison + Claude
**Status**: Draft

---

## Problem

The existing `docs/archive/EPICS.md` (30 DEC 2025) describes a different platform — one with Service Bus queues, a planned Reader Function App, ADF copy pipelines, and 11 Epics with 63 Features. Since then:

- The entire DAG orchestration system was built from scratch (Epoch 5)
- 10 YAML workflows and 58 handlers deployed and proven E2E
- 70+ adversarial code reviews (COMPETE/SIEGE/REFLEXION)
- Architecture migrated from Function Apps + Service Bus to Docker Workers + DAG Brain + PostgreSQL polling
- Admin UI, Zarr support, unpublish pipelines, approval gates, scheduled workflows all shipped

The old doc structure (11 epics, story-level detail inline) went stale within weeks and no longer reflects the product.

## Goal

Create a new SAFe documentation set that:

1. Accurately represents the platform as of v0.10.9
2. Organizes by **data domain** (vector, raster, multidim) + **lifecycle** + **platform ops** — matching how the audience thinks about the system
3. Separates stable master docs (Epic/Feature level) from volatile story docs
4. Is maintainable — the master registry should survive 3 months without an update

## Audience

| Persona | What They Need |
|---------|---------------|
| Technical counterparts (team) | Understand scope, capabilities, architecture maturity |
| Manager | See progress, value delivered, what's next |
| Future developers / Claude | SAFe tracking, story status, where to find things |
| Clients (later) | Not primary audience now; F1-F3 structure anticipates this |

## SAFe Hierarchy

```
Epic: Geospatial Backend Solution
  Epic ID: [TBD — new corporate ID]
  │
  ├── F1: Vector Data & Serving
  ├── F2: Raster Data & Serving
  ├── F3: Multidimensional Data & Serving
  ├── F4: Asset Lifecycle Management
  ├── F5: Platform & Operations
  │
  └── Enablers: EN1-ENx (infrastructure plumbing)
```

**Persona mapping**:
- F1-F3: Data scientists — "what can this platform do with my data?"
- F4: Data owners — "what happens after I submit? Who approves? Can I unpublish?"
- F5: Platform operators — "how do I monitor, schedule, manage?"

## Document Structure

```
docs/product/
├── PRODUCT_OVERVIEW.md              # Narrative: what is this platform
├── EPICS.md                         # Master registry: 1 Epic, 5 Features, Enablers
├── STORIES_F1_VECTOR.md             # Vector Data & Serving stories
├── STORIES_F2_RASTER.md             # Raster Data & Serving stories
├── STORIES_F3_MULTIDIM.md           # Multidimensional Data & Serving stories
├── STORIES_F4_LIFECYCLE.md          # Asset Lifecycle Management stories
└── STORIES_F5_PLATFORM.md           # Platform & Operations stories
```

Old `docs/archive/EPICS.md` remains archived, untouched.

## Document Specifications

### PRODUCT_OVERVIEW.md

**Purpose**: "Read this first" narrative for someone joining the team or a manager wanting the elevator pitch. Not SAFe tracking — the story.

**Sections**:
1. **What This Is** — 2-3 paragraphs: geospatial ETL platform, Bronze to Silver to Gold, turns raw data into standards-compliant APIs (OGC Features, STAC, TiTiler tiles)
2. **Architecture (Current State)** — 4-app architecture diagram (Function App, DAG Brain, Docker Worker, TiTiler). PostgreSQL as single source of truth, SKIP LOCKED polling. Brief strangler fig migration note.
3. **What It Processes** — Table: data type, input formats, output format, API surface
4. **Feature Map** — F1-F5 one-liner each with status badge, linking to EPICS.md
5. **Architecture Migration** — Where we came from, where we are, where we're going (v0.11.0)
6. **Quality Assurance** — COMPETE/SIEGE/REFLEXION summary. 70+ reviews, 83 fixes. Sells maturity.
7. **Technology Stack** — Table
8. **Deployment Model** — Brief, links to existing DEPLOYMENT_GUIDE.md

**Tone**: Technical but accessible. A senior engineer reads it in 10 minutes.

**Length target**: ~3-4 pages

### EPICS.md

**Purpose**: Master registry. One page, everything at a glance. Survives 3 months without update.

**Sections**:
1. **Header** — Epic name, Epic ID [TBD], last updated date
2. **WSJF Priority Matrix** — Table: Feature #, name, status badge, story count, WSJF score
3. **Feature Summaries** — 1-2 paragraphs per feature: what it delivers, current status, key capabilities
4. **Enablers** — Table: ID, name, status, what it enables
5. **Story Index** — Flat table: story ID, title, feature, status. One line per story. No detail.

**Key property**: No story detail. IDs, titles, status markers only.

### STORIES_F{n}_{NAME}.md (5 files, common template)

**Purpose**: Volatile detail docs. Can go stale without corrupting master registry.

**Template**:
1. **Header** — Feature name, parent Epic ref, last updated, status badge
2. **Feature Description** — 2-3 paragraphs: what this feature delivers, who cares, how it fits
3. **Stories Table** — ID, title, status, version delivered, notes
4. **Story Detail** (per story) — Status, acceptance criteria, key files, workflows, handlers

**Content mapping by feature**:

#### F1: Vector Data & Serving (~12 stories)
- S1.1: Vector ETL pipeline (load, validate, PostGIS)
- S1.2: OGC Features API (TiPG integration)
- S1.3: Multi-format support (SHP/GeoJSON/GPKG/CSV/KML)
- S1.4: Split views (single file to N OGC collections by column)
- S1.5: Multi-source vector (N files to N tables, GPKG multi-layer)
- S1.6: TiPG two-phase discovery (browsable pre-approval, searchable post-approval)
- S1.7: Vector unpublish pipeline
- S1.8: ACLED scheduled sync (API-driven recurring ingest)
- S1.9: Catalog registration (geo.table_catalog)
- S1.10: Vector DAG workflow (6-node, conditional branching)
- S1.11: Vector map viewer
- S1.12: Enhanced data validation

#### F2: Raster Data & Serving (~14 stories)
- S2.1: Single raster pipeline (GeoTIFF to COG)
- S2.2: Large raster support (>2GB conditional tiling, fan-out/fan-in)
- S2.3: Raster collection pipeline (N files, 5 fan-out/fan-in phases)
- S2.4: TiTiler integration (dynamic tile serving)
- S2.5: STAC integration (item + collection materialization)
- S2.6: COG compression tiers (analysis/visualization/archive)
- S2.7: Raster unpublish pipeline
- S2.8: Raster DAG workflow (12-node, most complex)
- S2.9: pgSTAC search registration (mosaic endpoints)
- S2.10: Raster map viewer (collection-aware)
- S2.11: Raster data extract API (point, clip, preview)
- S2.12: Raster classification and detection — planned
- S2.13: FATHOM ETL Phase 1 (band stacking)
- S2.14: FATHOM ETL Phase 2 (spatial merge) — partial

#### F3: Multidimensional Data & Serving (~10 stories)
- S3.1: Native Zarr ingest (cloud-native passthrough for abfs:// URLs)
- S3.2: NetCDF to Zarr conversion (rechunking, flat v3)
- S3.3: Zarr v3 consolidation fix
- S3.4: TiTiler xarray integration (tile serving for Zarr)
- S3.5: VirtualiZarr pipeline (lazy reference stores)
- S3.6: Zarr unpublish pipeline
- S3.7: Zarr observability (checkpoint events)
- S3.8: xarray service layer (point, statistics, aggregate endpoints)
- S3.9: CMIP6 data hosting — planned
- S3.10: TiTiler unified services (COG + Zarr) — planned

#### F4: Asset Lifecycle Management (~8 stories)
- S4.1: Asset/Release entity model (stable identity + versioned releases)
- S4.2: Approval workflow (draft to approved to revoked state machine)
- S4.3: STAC materialization at approval (deferred publishing)
- S4.4: Release audit trail (append-only lifecycle logging)
- S4.5: Unpublish orchestration (symmetric teardown, all data types)
- S4.6: Version ordinal management (reservation at submit, assignment at approval)
- S4.7: Services block gating (services=null until approval)
- S4.8: Approval guard (Epoch 4 vs DAG-aware processing_status)

#### F5: Platform & Operations (~11 stories)
- S5.1: DAG orchestration engine (YAML, conditionals, fan-out/fan-in, gates)
- S5.2: DAG Brain admin UI (dashboard, submit, approve/reject/revoke, handlers)
- S5.3: Scheduled workflows (cron-based DAGScheduler)
- S5.4: Health and preflight system (20 plugin checks, mode-aware)
- S5.5: 3-tier observability (logging, checkpoints, status integration)
- S5.6: API surface (115+ endpoints: platform, STAC, DAG, admin, OGC Features)
- S5.7: Schema management (ensure/rebuild DDL, 5-schema architecture)
- S5.8: Worker dual-poll (legacy + DAG task claiming)
- S5.9: Janitor (stale task recovery)
- S5.10: COMPETE/SIEGE quality pipeline (70+ adversarial reviews)
- S5.11: Deployment tooling (deploy.sh, health checks, version verification)

### Enablers (tracked in EPICS.md, no separate doc)

| ID | Name | Status | Enables |
|----|------|--------|---------|
| EN1 | Database Architecture (5-schema PostgreSQL) | Done | All |
| EN2 | Connection Pool and Auth (ManagedIdentityAuth, ConnectionManager, circuit breaker) | Done | All |
| EN3 | Docker Worker Infrastructure (ACR image, APP_MODE routing) | Done | F1-F3, F5 |
| EN4 | Configuration System (modular Pydantic config) | Done | All |
| EN5 | Deployment Tooling (deploy.sh, health checks) | Done | All |
| EN6 | Azure Blob Storage (BlobRepository, zone-based auth) | Done | F1-F3 |
| EN7 | Service Bus (deprecated, removal in v0.11.0) | Deprecated | Legacy |
| EN8 | Pre-flight Validation (blob_exists, collection_exists) | Done | F1-F3 |

## Status Badges

Consistent across all documents:

| Badge | Meaning |
|-------|---------|
| Done | Complete, deployed, proven |
| Operational | Feature-level: all core stories done |
| Partial | Feature-level: some stories done, some planned |
| In Progress | Actively being worked |
| Planned | Defined but not started |
| Deprecated | Being removed |

## WSJF Scores

To be calculated with Robert during implementation. Placeholder column in EPICS.md.

## Cross-References

- PRODUCT_OVERVIEW.md links to EPICS.md for SAFe detail
- EPICS.md links to each STORIES_F{n}.md for story detail
- STORIES docs link to existing `docs_claude/` technical references (ARCHITECTURE_REFERENCE.md, WORKFLOW_YAML_REFERENCE.md, etc.) for implementation detail
- No duplication of content from `docs_claude/` — link, don't copy

## What We Are NOT Doing

- Not updating `docs_claude/` docs (they serve a different purpose)
- Not creating client-facing documentation (comes later)
- Not deleting the archived EPICS.md
- Not tracking sprint-level tasks (that's GitHub Projects / TODO.md)
- Not going below story level (no acceptance criteria in master doc)
