# SAFe Epic & Feature Registry

**Last Updated**: 30 DEC 2025
**Framework**: SAFe (Scaled Agile Framework)
**Purpose**: Master reference for Azure DevOps Boards import
**Source of Truth**: This directory defines Epic/Feature numbers; TODO.md should align

---

## Quick Reference

**FY26 Target (ends 30 JUN 2026)**: E1 ✅, E2, E3, E4

| Priority | Epic | Name | Status | Features | WSJF | Link |
|:--------:|------|------|--------|:--------:|:----:|:----:|
| — | E1 | Vector Data as API | 🚧 Partial | 8 | — | [E1](E1_vector_data.md) |
| 1 | E2 | Raster Data as API | 🚧 Partial | 8 | 5.9 | [E2](E2_raster_data.md) |
| 2 | E3 | DDH Platform Integration | 🚧 Partial | 8 | 4.8 | [E3](E3_ddh_integration.md) |
| 3 | E4 | Data Externalization & Security Zones | 🚧 Partial | 5 | 4.3 | [E4](E4_security_zones.md) |
| 4 | E9 | Large and Multidimensional Data | 🚧 Partial | 7 | 2.5 | [E9](E9_large_data.md) |
| 5 | E8 | GeoAnalytics Pipeline | 🚧 Partial | 12 | 1.8 | [E8](E8_geoanalytics.md) |
| 6 | E7 | Pipeline Infrastructure | 🚧 Partial | 5 | — | [E7](E7_pipeline_infra.md) |
| — | E12 | Interface Modernization | ✅ Phase 1 | 5 | — | [E12](E12_interfaces.md) |

**Consolidated Epics** (absorbed into E1, E7, E8, or E9):
- ~~E5~~ → F1.7-F1.8 (OGC Styles) - now in E1
- ~~E10~~ → F9.1 (FATHOM ETL Operations) - now in E9
- ~~E11~~ → F8.10-12 (Analytics UI: Data Browser, H3 Visualization, Export)
- ~~E13~~ → F7.4 (Pipeline Observability)
- ~~E14~~ → F8.9 (H3 Export Pipeline)
- ~~E15~~ → F7.3 (Collection Ingestion)

**Epic Structure** (30 DEC 2025 restructure):
- **E7**: Pipeline Infrastructure — generic orchestration enablers (observability, builder, ingestion)
- **E8**: GeoAnalytics Pipeline — H3 aggregation, GeoParquet export, OGC Features output
- **E9**: Large and Multidimensional Data — hosting FATHOM + CMIP6 + VirtualiZarr datasets

```
E9: Large Data (FATHOM, CMIP6)  →  E8: GeoAnalytics  →  GeoParquet / OGC Features
         ↑                                                      ↓
    E7: Pipeline Infrastructure                         Databricks / DuckDB
         (enables both)                                       Maps
```

---

## WSJF Calculation

**Formula**: WSJF = Cost of Delay ÷ Job Size (higher score = do first)

**Cost of Delay** = Business Value + Time Criticality + Risk Reduction (each 1-21 Fibonacci)

| Epic | Business Value | Time Crit | Risk Red | **CoD** | Job Size | **WSJF** |
|------|:--------------:|:---------:|:--------:|:-------:|:--------:|:--------:|
| E2 | 21 (platform foundation) | 13 (FATHOM blocked) | 13 (enables downstream) | **47** | 8 | **5.9** |
| E3 | 21 (analytics front-end) | 13 (high urgency) | 13 (observability+diagnostics) | **48** | 10 | **4.8** |
| E4 | 13 (external access) | 8 (post-platform) | 13 (security/audit) | **34** | 8 | **4.3** |
| E9 | 13 (CMIP client priority) | 5 (secondary tier) | 8 (technical complexity) | **26** | 13 | **2.0** |
| E7 | 5 (operational efficiency) | 3 | 5 | **13** | 5 | **2.6** |
| E8 | 8 (analytics capability) | 3 | 5 | **16** | 13 | **1.2** |

**WSJF-Ordered Sequence**: E2 (5.9) → E3 (4.8) → E4 (4.3) → E7 (2.6) → E9 (2.0) → E8 (1.2)

**Note**: E3 absorbs former E6 (Platform Observability) — observability is app-to-app monitoring that enables integration.

---

## Enablers

| Enabler | Name | Status | Enables | Link |
|---------|------|--------|---------|:----:|
| EN1 | Job Orchestration Engine | ✅ Complete | E1, E2, E9 | [Details](ENABLERS.md#enabler-en1-job-orchestration-engine-) |
| EN2 | Database Architecture | ✅ Complete | All | [Details](ENABLERS.md#enabler-en2-database-architecture-) |
| EN3 | Azure Platform Integration | ✅ Complete | All | [Details](ENABLERS.md#enabler-en3-azure-platform-integration-) |
| EN4 | Configuration System | ✅ Complete | All | [Details](ENABLERS.md#enabler-en4-configuration-system-) |
| EN5 | Pre-flight Validation | ✅ Complete | E1, E2 | [Details](ENABLERS.md#enabler-en5-pre-flight-validation-) |
| EN6 | Long-Running Task Infrastructure | ⏳ FY26 Decision | E2, E9 | [Details](ENABLERS.md#enabler-en6-long-running-task-infrastructure--fy26-decision-pending) |

---

# COMPONENT GLOSSARY

Abstract component names for ADO work items. Actual Azure resource names assigned during implementation.

## Storage

| Logical Name | Purpose | Access Pattern | Zone |
|--------------|---------|----------------|------|
| **Bronze Storage Account** | Raw uploaded data | Write: ETL jobs, Read: processing | Internal |
| **Silver Storage Account** | Processed COGs, Zarr | Write: ETL jobs, Read: TiTiler, APIs | Internal |
| **External Storage Account** | Public-facing data | Write: ADF copy, Read: CDN/External Reader | External |

## Compute

| Logical Name | Purpose | Runtime | Status |
|--------------|---------|---------|--------|
| **ETL Function App** | Job orchestration, HTTP APIs | Azure Functions (Python) | ✅ Deployed |
| **Reader Function App** | Read-only data access APIs | Azure Functions (Python) | 📋 Planned |
| **Long-Running Worker** | Tasks exceeding 30-min timeout | Docker Container App | ⏳ FY26 Decision |
| **TiTiler Raster Service** | COG tile serving | Docker Container App | ✅ Deployed |
| **TiTiler Zarr Service** | Zarr/NetCDF tile serving | Docker Container App | 📋 Planned |

### Docker Deployments Detail

| Service | Image Source | Deployment Target | Notes |
|---------|--------------|-------------------|-------|
| **TiTiler Raster** | `ghcr.io/stac-utils/titiler-pgstac` | Azure Container Apps | Production, serving COGs |
| **TiTiler Zarr** | Custom (xarray/zarr stack) | Azure Container Apps | Pending E9 progress |
| **Long-Running Worker** | Custom (GDAL/rasterio stack) | Azure Container Apps | See EN6; FY26 decision pending |

## Queues (Service Bus)

| Logical Name | Purpose |
|--------------|---------|
| **Job Queue** | Initial job submission |
| **Vector Task Queue** | Vector processing tasks |
| **Raster Task Queue** | Raster processing tasks |
| **Long-Running Task Queue** | Overflow to Docker worker |

## Database

| Logical Name | Purpose | Zone |
|--------------|---------|------|
| **App Database** | Job/task state, curated datasets (nukeable) | Internal |
| **Business Database** | PostGIS geo schema, pgSTAC catalog (protected) | Internal |
| **External Database** | External PostgreSQL with PostGIS for public data | External |
| **App Admin Identity** | Managed identity with DDL privileges | Internal |
| **App Reader Identity** | Managed identity with read-only privileges | Internal |
| **External Reader Identity** | Managed identity for external zone read access | External |

## External Systems

| Logical Name | Purpose |
|--------------|---------|
| **DDH Application** | Data Hub Dashboard — separate app, separate identity, already exists |
| **DDH Managed Identity** | DDH's own identity (already exists) — needs RBAC grants to platform resources |
| **CDN/WAF** | Cloudflare edge protection for external zone |
| **Data Factory Instance** | ADF for blob-to-blob copy operations |

---

## Directory Structure

```
docs/epics/
├── README.md              # This file - Quick Reference + Navigation
├── E1_vector_data.md      # Epic E1: Vector Data as API (includes OGC Styles)
├── E2_raster_data.md      # Epic E2: Raster Data as API
├── E3_ddh_integration.md  # Epic E3: DDH Platform Integration
├── E4_security_zones.md   # Epic E4: Data Externalization & Security Zones
├── E7_pipeline_infra.md   # Epic E7: Pipeline Infrastructure
├── E8_geoanalytics.md     # Epic E8: GeoAnalytics Pipeline
├── E9_large_data.md       # Epic E9: Large and Multidimensional Data
├── E12_interfaces.md      # Epic E12: Interface Modernization
└── ENABLERS.md            # Technical foundation enablers (EN1-EN6)
```

---

## For Azure DevOps Import

**Work Item Type Mapping**:
| EPICS.md Term | ADO Work Item Type |
|---------------|--------------------|
| Epic (E1, E2, etc.) | Epic |
| Feature (F1.1, F2.1, etc.) | Feature |
| User Story | Story (S1.1.1, S2.1.1, etc.) |
| Task | Enabler tasks |

**Cross-Team Assignment**:
- E3 (DDH Platform Integration) → Assign to DDH Team in ADO
- All other Epics → Assign to Geospatial Team
