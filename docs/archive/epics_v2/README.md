# Geospatial Platform - Epic Portfolio

**Last Updated**: 30 JAN 2026
**Architecture Version**: V0.8
**ADO Epic**: "Geospatial API for DDH"

> **ADO Migration**: These docs are being migrated to Azure DevOps. See `V0.8_ADO.md` for migration plan. WB Claude will configure ADO using these docs as specification.

---

## Platform Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         ETL PLATFORM (rmhgeoapi)                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   Platform Gateway ──▶ geospatial-jobs ──▶ Orchestrator (CoreMachine)       │
│   (E3, E4, E12)           (queue)              (E7)                         │
│                                                   │                          │
│                               ┌───────────────────┴───────────────────┐      │
│                               ▼                                       ▼      │
│                      container-tasks                        functionapp-tasks│
│                          (queue)                                (queue)      │
│                               │                                       │      │
│                               ▼                                       ▼      │
│                       Docker Worker                        FunctionApp Worker│
│                     (E1, E2, E8, E9)                      (lightweight ops)  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                       SERVICE LAYER (rmhtitiler) - E6                        │
├─────────────────────────────────────────────────────────────────────────────┤
│   TiTiler (COG tiles, xarray, pgSTAC)  │  TiPG (OGC Features, MVT)          │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Epic Summary

| Epic | Name | ADO Feature | Status | Value Stream |
|------|------|-------------|--------|--------------|
| **E1** | [Vector Data as API](E1_vector_data.md) | Vector Data Pipeline | ✅ | Data ingestion |
| **E2** | [Raster Data as API](E2_raster_data.md) | Raster Data Pipeline | ✅ | Data ingestion |
| **E3** | [DDH Integration](E3_ddh_integration.md) | DDH Platform Integration | 🚧 50% | Cross-team coordination |
| **E4** | [Security & Externalization](E4_security.md) | Security & Data Classification | 🚧 67% | Compliance |
| **E6** | [Service Layer (B2C)](E6_service_layer.md) | Consumer APIs (TiTiler/TiPG) | ✅ | Consumer access |
| **E7** | [Pipeline Infrastructure](E7_pipeline_infra.md) | ETL Pipeline Infrastructure | ✅ | Platform capability |
| **E8** | [GeoAnalytics](E8_geoanalytics.md) | H3 Analytics Pipeline | 🚧 57% | Derived products |
| **E9** | [Large & Multidimensional](E9_large_data.md) | Large Dataset Processing | 🚧 20% | Specialized ingestion |
| **E12** | [Admin Interface (B2B)](E12_admin_interface.md) | Operator Admin Portal | ✅ | Operator tools |

---

## Value Stream Map

```
Data Publishers                    Platform                         Consumers
─────────────────                  ────────                         ─────────

  Raw Files ────▶ E1 Vector ETL ───┐
                                   │
  Raw Files ────▶ E2 Raster ETL ───┼───▶ E7 Pipeline ───▶ E6 Service Layer ───▶ B2C
                                   │      Infrastructure    (TiTiler/TiPG)
  FATHOM/CMIP6 ─▶ E9 Large Data ───┤
                                   │
                  E8 Analytics ────┘
                  (H3 aggregation)


Cross-Cutting:
  E3 DDH Integration ──── External team coordination
  E4 Security ─────────── Classification, approval, ADF
  E12 Admin Interface ─── Operator tools (B2B)
```

---

## Epic Dependencies

```
              ┌─────────────────────────────────────┐
              │         E7: Pipeline Infrastructure │ ◀── Foundation
              │    (CoreMachine, Docker, Queues)    │
              └─────────────────┬───────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
        ▼                       ▼                       ▼
┌───────────────┐     ┌───────────────┐     ┌───────────────┐
│ E1: Vector    │     │ E2: Raster    │     │ E9: Large     │
│ Data as API   │     │ Data as API   │     │ Data          │
└───────┬───────┘     └───────┬───────┘     └───────┬───────┘
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │ E8: GeoAnalytics  │
                    │ (H3 aggregation)  │
                    └─────────┬─────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │ E6: Service Layer │ ◀── B2C Access
                    │ (TiTiler, TiPG)   │
                    └───────────────────┘
```

---

## Implementation Details

All implementation specifications are in `docs_claude/`:

| Topic | Document |
|-------|----------|
| CoreMachine | `ARCHITECTURE_REFERENCE.md` |
| Docker Worker | `DOCKER_INTEGRATION.md` |
| Queue Architecture | `V0.8_PLAN.md` (root) |
| Metadata | `RASTER_METADATA.md` |
| Approval Workflow | `APPROVAL_WORKFLOW.md` |
| Classification | `CLASSIFICATION_ENFORCEMENT.md` |
| FATHOM Pipeline | `FATHOM_ETL.md` |

---

## Archive

Previous epic versions: `docs/archive/epics_v1/`
