# Geospatial Platform - Epic Portfolio

**Last Updated**: 24 JAN 2026
**Architecture Version**: V0.8

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

| Epic | Name | Type | Status | Value Stream |
|------|------|------|--------|--------------|
| **E1** | [Vector Data as API](E1_vector_data.md) | Business | ✅ | Data ingestion |
| **E2** | [Raster Data as API](E2_raster_data.md) | Business | ✅ | Data ingestion |
| **E3** | [DDH Integration](E3_ddh_integration.md) | Enabler | 🚧 | Cross-team coordination |
| **E4** | [Security & Externalization](E4_security.md) | Enabler | 🚧 | Compliance |
| **E6** | [Service Layer (B2C)](E6_service_layer.md) | Platform | ✅ | Consumer access |
| **E7** | [Pipeline Infrastructure](E7_pipeline_infra.md) | Foundational | ✅ | Platform capability |
| **E8** | [GeoAnalytics](E8_geoanalytics.md) | Business | 🚧 | Derived products |
| **E9** | [Large & Multidimensional](E9_large_data.md) | Business | 🚧 | Specialized ingestion |
| **E12** | [Admin Interface (B2B)](E12_admin_interface.md) | Enabler | 🚧 | Operator tools |

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
