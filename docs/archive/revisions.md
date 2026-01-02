# Geospatial Platform SAFe Portfolio

## Overview

This document defines the Epic portfolio structure for the World Bank Geospatial Platform (DDHGeo/Chimera). It serves as a reference for Claude assistants and Robert when planning, prioritizing, and discussing work.

**Context**: This platform is the geospatial backend for Data360, the World Bank's flagship data analytics platform. The architecture replaces expensive ESRI Enterprise infrastructure with cloud-native serverless solutions (Azure Functions, PostGIS, TiTiler, STAC catalogs).

---

## Portfolio Data Flow

```
╔═════════════════════════════════════════════════════════════════════╗
║                 E7: PIPELINE INFRASTRUCTURE                         ║
║                      (FOUNDATIONAL LAYER)                           ║
║                                                                     ║
║   • Data type inference ("RGB imagery" / "multispectral" / "DEM")   ║
║   • Validation logic (garbage KML → beautiful PostGIS)              ║
║   • Job orchestration (Durable Functions + Service Bus)             ║
║   • Advisory locks for distributed coordination                     ║
║   • Fan-out patterns for parallel processing                        ║
║                                                                     ║
║   This is the ETL brain. All other Epics run on this substrate.     ║
╚══════════════════════════════════╦══════════════════════════════════╝
                                   ║
         ┌─────────────────────────╬─────────────────────────┐
         ▼                         ▼                         ▼
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│   E1: Vector    │      │   E2: Raster    │      │   E9: Large &   │
│                 │      │                 │      │   Multidim      │
│ CSV,KML,SHP,    │      │ GeoTIFF → COG   │      │                 │
│ GeoJSON →       │      │ → TiTiler       │      │ FATHOM, CMIP6   │
│ PostGIS + OGC   │      │                 │      │ Zarr/NetCDF     │
└────────┬────────┘      └────────┬────────┘      └────────┬────────┘
         │                        │                        │
         └────────────────────────┼────────────────────────┘
                                  ▼
                    ┌─────────────────────────┐
                    │   E8: GeoAnalytics      │
                    │                         │
                    │   H3 Aggregation →      │
                    │   GeoParquet / OGC      │
                    └────────────┬────────────┘
                                 │
        ┌────────────────────────┼────────────────────────┐
        ▼                        ▼                        ▼
┌───────────────┐      ┌─────────────────┐      ┌─────────────────────┐
│  E3: DDH      │      │ E4: External    │      │ E12: Integration    │
│  Integration  │      │ Security Zones  │      │ Onboarding UI       │
│  (political)  │      │                 │      │                     │
│               │      │ ADF pipelines   │      │ "Hi! Here's how to  │
│  One foreign  │      │ between zones   │      │ integrate me!"      │
│  key. Done.   │      │                 │      │ [CURL] [Click me]   │
└───────────────┘      └─────────────────┘      └─────────────────────┘
```

---

## Epic Portfolio Summary

| Epic | Name | Type | Value Stream | Status |
|------|------|------|--------------|--------|
| E7 | Pipeline Infrastructure | **Enabler (Foundation)** | Platform | 🚧 Partial |
| E1 | Vector Data | Business | Data Ingestion | ✅ Active |
| E2 | Raster Data | Business | Data Ingestion | ✅ Active |
| E9 | Large & Multidimensional Data | Business | Data Hosting | 🚧 Partial |
| E8 | GeoAnalytics Pipeline | Business | Data Transform | 🚧 Partial |
| E12 | Integration Onboarding UI | Enabler | Operations | 🚧 Partial |
| E3 | DDH Integration | Political | Integration | 🔄 Dependency |
| E4 | Externalization & Security | Enabler | Security | 📋 Planned |

---

## Epic Definitions

### E7: Pipeline Infrastructure 🚧 (FOUNDATIONAL)

**Value Statement**: The ETL brain that makes everything else possible.

**Business Requirement**: Generic pipeline orchestration infrastructure — data type inference, validation, job management, fan-out patterns, observability.

**Type**: Foundational Enabler Epic

**This is the substrate.** E1, E2, E8, and E9 all run on E7. Without it, nothing processes.

**Core Capabilities**:

| Capability | What It Does |
|------------|--------------|
| Data type inference | "This is RGB imagery" / "This is some multispectral mess" / "This is probably a DEM" |
| Validation logic | Garbage KML (redundant nodes, broken geometries) → beautiful PostGIS tables |
| Job orchestration | Durable Functions + Service Bus coordination |
| Advisory locks | PostgreSQL-based distributed coordination (the "oops" we invented) |
| Fan-out patterns | Parallel task processing with controlled concurrency |
| Pipeline builder UI | Visual orchestration management |
| Observability | Job state tracking, monitoring, failure handling |

**Why it's separate from E1/E2**: The orchestration system serves *all* data pipelines. It's not "vector ETL" or "raster ETL" — it's the engine that runs both. Cross-cutting infrastructure deserves its own Epic.

**The emotional core**: This is the aspect Robert feels most strongly about. The patterns here — advisory locks, Service Bus queues, fan-out coordination — are the hard-won architectural innovations that make the platform work at scale.

---

### E1: Vector Data ✅

**Value Statement**: Any vector garbage you throw at us becomes clean, standardized, API-accessible data.

**Business Requirement**: CSV, KML, SHP, GeoJSON, assorted geo-junk files in → standardized cleaned PostGIS tables accessible via OGC Feature implementation out.

**Runs on**: E7 (Pipeline Infrastructure)

**Why it's an Epic**: This is a strategic capability. Stakeholders can point at it and say "yes, that's what I want." It represents a complete value stream from messy input to clean API output.

---

### E2: Raster Data ✅

**Value Statement**: Any imagery you have becomes analysis-ready and visualizable.

**Business Requirement**: GeoTIFFs in → validated categorized COGs accessible via TiTiler (and future raster stats API) out.

**Runs on**: E7 (Pipeline Infrastructure)

**Why it's an Epic**: Like E1, this is a complete value stream. The underlying complexity (ETL pipeline, TiTiler customization, managed identity, STAC integration) are Features within this Epic, not separate Epics.

**Example Feature decomposition**:
```
Epic 2: Raster Data
├── Feature: Raster ETL Pipeline
│   ├── Story: COG validation logic
│   ├── Story: Blob storage organization
│   └── Story: Metadata extraction
├── Feature: TiTiler Deployment
│   ├── Story: Managed identity integration
│   ├── Story: Mosaic configuration
│   └── Story: Performance tuning
├── Feature: STAC Catalog
└── Feature: Raster Stats API (future)
```

---

### E9: Large and Multidimensional Data 🚧

**Value Statement**: We can host and serve FATHOM/CMIP6-scale data.

**Business Requirement**: Host and serve massive GeoTIFF and Zarr/NetCDF datasets at scale.

**Runs on**: E7 (Pipeline Infrastructure)

**Strategic Context**: E9 is the "data hosting" epic. It handles ingesting, processing, and serving very large datasets that feed into E8 (GeoAnalytics). First prototypes:
- FATHOM flood data (GeoTIFF)
- CMIP6 climate data (Zarr/NetCDF)
- VirtualiZarr pipeline enables serving NetCDF without conversion

**Relationship to E8**: E9 hosts → E8 transforms. Without E9, E8 has nothing to process.

---

### E8: GeoAnalytics Pipeline 🚧

**Value Statement**: Raw hosted data becomes H3-aggregated, analysis-ready output.

**Business Requirement**: Transform raster/vector data to H3 hexagonal grid, export to GeoParquet and OGC Features.

**Runs on**: E7 (Pipeline Infrastructure)

**Strategic Context**: E8 is the "transform and export" epic. Data hosted in E9 (FATHOM, CMIP6) gets aggregated to H3 hexagons and exported as:
- Gargantuan GeoParquet files (res 2-8, hundreds of columns) for Databricks/DuckDB
- OGC Feature collections for mapping and download

**Why it matters**: This is what the client actually wants even if they can't articulate "H3 hierarchical grid aggregation pipelines outputting GeoParquet for Databricks consumption." They'll say "we need analytics" — E8 is the answer.

**The Development Seed reality**: People are paying premium rates for this work. But once you know the pattern — H3 resolution selection, efficient polygon-to-cell algorithms, aggregation strategies — it's just compute. Azure Functions with chunked processing will get you there.

---

### E12: Integration Onboarding UI 🚧

**Value Statement**: "Hi! Here's how to integrate me! Click me for more details!"

**Business Requirement**: Interactive system administration dashboard that walks users through integration patterns.

**Type**: Enabler (Operational + Strategic)

**What it actually is**: This isn't an admin dashboard. It's an *onboarding experience* for anyone integrating with the platform. Every button shows the raw API call (CURL command in a nearby box). It's designed to:

1. Enable operators to manage pipelines without CLI/database access
2. **Teach other teams how to integrate** — this is the real purpose
3. Define the interaction patterns DDH will eventually implement
4. Be so helpful that copying it is the path of least resistance

**The CURL box strategy**: 

```
┌─────────────────────────────────────────────────────┐
│  [Trigger FATHOM Processing]                        │
│                                                     │
│  curl -X POST https://api.geo.worldbank.org/jobs   │
│    -H "Authorization: Bearer $TOKEN"                │
│    -d '{"pipeline": "fathom", "region": "SSA"}'    │
│                                                     │
│  📋 Copy to clipboard                               │
└─────────────────────────────────────────────────────┘
```

Every button says "this is what you would copy." When ITSDA copies this UI, they're copying example code that calls *your* APIs with *your* contracts. Every button they replicate embeds your interface spec deeper into their application.

**The political framing**:

"Are you building a competing frontend?"

"No, this is developer tooling. Every action shows the raw API call. It's designed to teach other teams how to integrate. It's basically Postman with better UX."

**The SAFe-compliant name**: "API Reference & Developer Tooling" — you're being helpful, reducing integration friction, being a team player.

---

### E3: DDH Integration 🔄

**Value Statement**: Metadata authority relationship is satisfied with minimal coupling.

**Business Requirement**: ITSDA makes changes to DDH (their app) to make calls to our app.

**Type**: Political Epic

**Why it exists**: This Epic tracks *their* work that affects us — and creates a paper trail. It makes visible:
- What ITSDA committed to
- Whether they delivered
- Where the blocker is when things stall

**The actual integration**: One foreign key. Links from our system go into DDH pages. That's it. Pipeline orchestration doesn't need to be driven by the ADLS ziggurat.

**SAFe utility**: In PI Planning, "E3 is blocked pending ITSDA deliverables" puts the dependency arrow on them.

**Candidate for closure**: Once integration is complete, this may fold into maintenance under E1/E2.

---

### E4: Externalization & Security Zones 📋

**Value Statement**: E1 and E2 capabilities become available externally.

**Business Requirement**: Enable external access to platform data via security zone architecture and ADF copy pipelines between storage zones.

**Type**: Enabler Epic

**Strategic Context**: Cross-cutting infrastructure for moving data from internal to external zones. Primarily ADF pipelines coordinating blob storage access across security boundaries.

**Candidate for consolidation**: Could merge into E7 (Platform Infrastructure), or close after externalization is complete (it's a project, not a permanent capability).

---

## SAFe Concepts Reference

### Epic vs Feature vs Story

| Level | Definition | Example |
|-------|------------|---------|
| **Epic** | Strategic capability a stakeholder would recognize as valuable | "Continental flood risk visualization" |
| **Feature** | Deliverable chunk, fits in a PI | "TiTiler deployment with managed identity" |
| **Story** | Work one person can finish in a sprint | "Configure mosaic JSON for FATHOM tiles" |

**The test**: Can you explain the value to a stakeholder in one sentence? If yes, it might be an Epic.

### Enablers

Work that doesn't deliver direct user value but makes future value delivery possible (or faster, or cheaper, or not a dumpster fire).

**This platform is mostly Enablers** — TiTiler infrastructure, Azure Functions orchestration, PostGIS setup. None of that is a "feature" an analyst would request. But without it, the features they want are impossible or cost 30x more.

**SAFe guidance**: Enablers should be ~20-30% of capacity. Platform/infrastructure teams are often 70%+ Enablers.

**E7 is the uber-Enabler**: It enables E1, E2, E8, and E9. Without E7, nothing runs.

### Spikes

Time-boxed research where the output is *knowledge*, not working code.

**When to use**: "I have no idea how long that will take because I don't know if X is even possible."

**Key attributes**:
- Time-boxed (1-3 days typically)
- Output is a decision or documented finding
- Gets estimated in points (consumes capacity)

### Value Streams

Instead of "what features should I build," ask "what's the flow of value from request to delivery?"

**This platform's value streams**:
1. Raw data arrives → Processed (E7) → Clean APIs (E1/E2) → Hosted at scale (E9) → Transformed (E8) → Consumed
2. Each Epic maps to a transformation step in that flow

---

## Political Context

### The Strategic Position

This platform is positioned as the geospatial backend for Data360. The client (DEC) wants it used for *all* geospatial data. This creates leverage:

- Anyone building features on geospatial data integrates with *us*
- The dependency arrow points at other teams, not us
- DDH integration = one foreign key, not architectural entanglement

### The ITSDA Dynamic

ITSDA was positioned as the "feature team" (visible client value) while this platform was cast as "enabler provider" (invisible infrastructure). That's an extractive arrangement.

**The countermove**: Vertical integration. This platform delivers features *directly* to clients. The storage environment isn't a "rogue platform" — it's the client-sanctioned canonical data layer.

### The Integration Onboarding Strategy (E12)

The UI demonstrates what the APIs can do. If ITSDA wants a frontend, they build against documented, stable endpoints. The integration surface is the API, not React components.

"Here's the TiTiler endpoint, here's the STAC catalog, here's the schema. Build whatever frontend you want. I'm not in the frontend business — I'm in the data platform business."

The CURL boxes are the Trojan horse. They say "this isn't a product, it's a reference" while simultaneously defining exactly how all future integration must work.

---

## Notes for Claude Assistants

When working on this platform:

1. **E7 is foundational**: It's not a peer to other Epics — it's the substrate they run on. Treat orchestration work as critical infrastructure.

2. **Epic stability**: Epics should be stable over a PI or two. If Epics keep changing, there's no strategy — just a to-do list.

3. **Feature refinement**: New ideas often start feeling like Epics, then get refined into Features under existing Epics. That's discovery, not disorganization.

4. **Dependency tracking**: E3 exists to make ITSDA dependencies visible. Use it.

5. **Enabler honesty**: Most work here is Enablers. Frame it correctly — "Platform Infrastructure" not "misc tasks."

6. **The client framing**: The client didn't ask for H3 aggregation pipelines. But they want "analytics" and this is what analytics requires. Build what they *should* want.

7. **E12 is strategic**: The "admin UI" is really integration onboarding. Every CURL box teaches the integration pattern. Treat it as documentation with buttons.

---

*Last Updated: December 2025*
*Portfolio Owner: Robert*