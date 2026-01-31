# Epic E12: Admin Interface (B2B)

**Type**: Enabler
**Status**: Operational
**Last Updated**: 30 JAN 2026
**ADO Feature**: "Operator Admin Portal"

---

## Value Statement

Self-service onboarding interface for platform operators and integrators. Every action shows the equivalent API call, teaching integration patterns while enabling operations.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      ADMIN INTERFACE (B2B)                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐          │
│   │ System          │   │ Pipeline        │   │ API             │          │
│   │ Dashboard       │   │ Workflow Hub    │   │ Documentation   │          │
│   │                 │   │                 │   │                 │          │
│   │ • Health status │   │ • Submit jobs   │   │ • Swagger UI    │          │
│   │ • Schema stats  │   │ • Monitor jobs  │   │ • Integration   │          │
│   │ • Queue status  │   │ • View results  │   │   guides        │          │
│   └─────────────────┘   └─────────────────┘   └─────────────────┘          │
│                                                                              │
│   ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐          │
│   │ STAC Browser    │   │ OGC Features    │   │ Approvals       │          │
│   │                 │   │ Browser         │   │ Queue           │          │
│   │ • Collections   │   │ • Collections   │   │ • Pending items │          │
│   │ • Items         │   │ • Feature count │   │ • Approve/reject│          │
│   │ • Preview       │   │ • Map view      │   │                 │          │
│   └─────────────────┘   └─────────────────┘   └─────────────────┘          │
│                                                                              │
│   Every button includes: [Action] + [CURL Box] + [Copy to clipboard]        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Key Principle**: This is an *onboarding experience*, not just an admin dashboard. Every action shows the raw API call so integrators learn by using.

---

## Features

| Feature | Status | Scope |
|---------|--------|-------|
| F12.1 HTMX Integration | ✅ | Interactive UI without custom JS |
| F12.2 System Dashboard | ✅ | Health, schema stats, queue status, cross-system view |
| F12.3 Pipeline Workflow Hub | ✅ | Job submission, monitoring, task viewer |
| F12.4 API Documentation Hub | ✅ | Swagger UI, OpenAPI spec |
| F12.5 STAC Browser | ✅ | Collection/item exploration, raster curator |
| F12.6 OGC Features Browser | ✅ | Vector collection exploration, vector curator |
| F12.7 Approvals Interface | 📋 | Pending approval queue (buttons exist, full UI pending) |

**Updated 30 JAN 2026**: F12.2-F12.6 completed as part of V0.8 Docker UI migration.

---

## Feature Summaries

### F12.1: HTMX Integration
Interactive UI patterns without custom JavaScript:
- Cascading dropdowns via `hx-get`
- Form submission via `hx-post`
- Auto-polling via `hx-trigger="every 5s"`

### F12.2: System Dashboard
Unified system health view:
- Architecture component map
- Health check status (database, storage, queues)
- Database schema statistics

### F12.3: Pipeline Workflow Hub
Job submission and monitoring:
- Workflow cards for each pipeline type
- Job submission forms with file browser
- Recent jobs table with status

### F12.4: API Documentation Hub
Self-service API documentation:
- Swagger UI: `/api/interface/swagger`
- OpenAPI JSON: `/api/openapi.json`
- Integration guides and examples

### F12.5 & F12.6: Data Browsers
Exploration interfaces for processed data:
- STAC collection/item browser with thumbnails
- OGC Features collection browser with counts
- Click-to-view on map

### F12.7: Approvals Interface (Planned)
Approval queue management:
- List pending approvals
- View dataset details
- Approve/reject with notes

---

## The CURL Box Strategy

Every action shows the equivalent API call:

```
┌─────────────────────────────────────────────────────┐
│  [Submit Vector Job]                                │
│                                                     │
│  curl -X POST https://api.geo.../platform/submit   │
│    -H "Content-Type: application/json"              │
│    -d '{"container": "bronze", "file": "data.shp"}'│
│                                                     │
│  📋 Copy to clipboard                               │
└─────────────────────────────────────────────────────┘
```

When integrators replicate this UI, they're copying example code that calls *your* APIs with *your* contracts.

---

## Target Audiences

| Audience | Primary Features |
|----------|-----------------|
| Platform Operators | Dashboard, Pipeline Hub, Approvals |
| Data Publishers | Pipeline Hub, STAC Browser |
| Integrators | API Docs, CURL examples |

---

## Dependencies

| Depends On | Enables |
|------------|---------|
| E7 Platform API | Operator self-service |
| E6 Service Layer | Data preview |

---

## Implementation Details

Built on Azure Functions + HTMX. See `web_interfaces/` for implementation.
