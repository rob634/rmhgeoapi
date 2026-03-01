# GREENFIELD: Platform Dashboard UI

**Date**: 01 MAR 2026
**Pipeline**: GREENFIELD (7-agent: S → A+C+O → M → B → V)
**Status**: SPEC READY — Awaiting Agent Dispatch
**Epic**: UI_REBUILD — Platform Dashboard
**Priority**: P1

---

## Executive Summary

Replace the existing 37-interface `web_interfaces/` system with a new consolidated **Platform Dashboard** (`web_dashboard/`). The old system remains accessible but is secondary/deprecated. The new dashboard is an **operator power-user tool** — dense information, quick actions, zero JavaScript framework overhead.

**Technology**: SSR Python + HTMX (proven pattern, zero build step, runs on Azure Function App)
**Layout**: Top tabs + sub-tabs + main content area
**Architecture**: Dashboard Shell + Panel Modules (Approach A)

---

## Table of Contents

1. [Tier 1: System Context](#tier-1-system-context)
2. [Tier 2: Design Constraints](#tier-2-design-constraints)
3. [Architecture Overview](#architecture-overview)
4. [Tab Structure & Pages](#tab-structure--pages)
5. [Style Scheme Variants](#style-scheme-variants)
6. [Data Flow & HTMX Patterns](#data-flow--htmx-patterns)
7. [API Endpoints Referenced](#api-endpoints-referenced)
8. [Success Criteria](#success-criteria)
9. [Open Questions](#open-questions)

---

## Tier 1: System Context

### What The Component Does

A new unified dashboard UI served from the same Azure Function App (Python). It provides:

1. **Platform Operations** (P1): Submit data, track requests, approve/reject releases, catalog lookup
2. **Job & Asset Monitoring** (P2): Job status dashboard, task drill-down, pipeline visualization, approval queue
3. **System Health** (P3): Database health, queue monitoring, STAC status, storage overview

### What It Connects To

| System | Connection | Purpose |
|--------|-----------|---------|
| Platform API | `/api/platform/*` (17 endpoints) | Submit, status, approve, catalog, lineage |
| Jobs API | `/api/jobs/*` + `/api/dbadmin/jobs` | Job monitoring, task drill-down |
| Assets API | `/api/assets/*` (7 endpoints) | Approval workflow, release management |
| STAC API | `/api/stac/*` (15 endpoints) | Collection/item browsing |
| DB Admin API | `/api/dbadmin/*` (18 endpoints) | Health, diagnostics, schema stats |
| Health Probes | `/health`, `/system-health` | System readiness |

### What Already Exists

**Current web_interfaces/ system (37 interfaces)**:
- `BaseInterface` abstract class (~1000 lines) with `InterfaceRegistry` decorator
- Server-side rendered HTML with HTMX for partial updates
- Design System CSS (Open Sans, navy/blue/cyan/gold palette)
- Served via `/api/interface/{name}` unified route
- Individual pages: home, health, jobs, tasks, STAC, vector, map, storage, submit, pipeline, etc.

**Why replace**:
- 37 separate interfaces = fragmented UX, no persistent chrome
- Each page is a full navigation event (even with HTMX)
- No unified state or context between pages
- Difficult to get an operational overview without clicking through 5+ pages

### What It Must Guarantee

1. **Coexistence**: Old `/api/interface/*` routes remain functional (deprecated, not removed)
2. **Zero Build Step**: No Node.js, no npm, no webpack — pure Python + HTML + HTMX
3. **Azure Function Compatible**: Runs as an HTTP trigger on the existing Function App
4. **Sub-Second Tab Switching**: HTMX fragment loading, not full page reloads
5. **Auto-Refresh**: Processing jobs and queue status update automatically (HTMX polling)
6. **Mobile Passable**: Not optimized for mobile, but shouldn't break on tablet

### Infrastructure Profile

- **Runtime**: Azure Function App (Python 3.12, Consumption plan)
- **No persistent state**: All data from API calls, no session storage
- **Cold start consideration**: Dashboard shell + one panel per request (not all panels)
- **Response size**: Target < 100KB per panel render (HTML + inline CSS/JS)

---

## Tier 2: Design Constraints

### Settled Architectural Patterns

1. **Registry Pattern**: Use a `PanelRegistry` decorator (similar to `InterfaceRegistry`) for panel auto-discovery
2. **BasePanel Class**: Abstract base providing common utilities (API calls, status badges, table rendering)
3. **HTMX Fragment Protocol**: Panels serve full HTML on initial load, fragments on `HX-Request` header
4. **Design System CSS**: Consolidated in the shell, not duplicated per panel
5. **Military Date Format**: All timestamps display as `01 MAR 2026`

### Integration Rules

1. Dashboard route: `GET /api/dashboard` (top-level, not under `/api/interface/`)
2. Panel fragments: `GET /api/dashboard?tab={name}&fragment={section}` (HTMX partials)
3. Action endpoints: Dashboard UI calls existing API endpoints (never bypasses to DB directly)
4. Error display: API errors shown inline with retry affordance, never raw stack traces

### Anti-Patterns (Do Not)

1. **No JavaScript frameworks** — No React, Vue, Svelte, Alpine.js
2. **No client-side routing** — HTMX handles all navigation via server fragments
3. **No CSS frameworks** — No Bootstrap, Tailwind, Bulma — custom design system only
4. **No WebSocket** — HTMX polling (5-10s intervals) for live data
5. **No local storage** — No client-side state persistence
6. **No build pipeline** — Everything is Python string templates or inline HTML

### Conventions

- Python files: `snake_case.py` with standard project file headers
- CSS: CSS custom properties (variables) for theming
- HTML IDs: `kebab-case` (e.g., `job-status-table`)
- HTMX attributes: Explicit `hx-get`, `hx-target`, `hx-swap`, `hx-trigger`

---

## Architecture Overview

### Directory Structure

```
web_dashboard/
├── __init__.py              # Route handler + panel registry + auto-import
├── shell.py                 # Dashboard chrome: tabs, sub-tabs, CSS, JS, HTML wrapper
├── base_panel.py            # Abstract BasePanel with common utilities
├── panels/
│   ├── __init__.py
│   ├── platform.py          # Tab 1: Platform operations
│   ├── jobs.py              # Tab 2: Job & task monitoring
│   ├── data.py              # Tab 3: Data browse (assets, STAC, vector)
│   └── system.py            # Tab 4: System health & admin
```

### Request Flow

```
Browser GET /api/dashboard
    → function_app.py route
    → web_dashboard.dashboard_handler(req)
    → DashboardShell.render(req, active_tab)
        → PanelRegistry.get(tab_name)
        → panel.render(req) or panel.fragment(req, fragment_name)
    → HttpResponse(html, content_type="text/html")
```

### HTMX Navigation Model

```
Initial Load:
  GET /api/dashboard → Full HTML (shell + default tab content)

Tab Switch:
  Click "Jobs" tab
  → hx-get="/api/dashboard?tab=jobs"
  → hx-target="#main-content"
  → hx-push-url="true"
  → Server returns: jobs panel HTML fragment
  → HTMX swaps #main-content, updates URL bar

Sub-Tab Switch:
  Click "Tasks" sub-tab within Jobs
  → hx-get="/api/dashboard?tab=jobs&section=tasks"
  → hx-target="#panel-content"
  → Server returns: tasks section HTML fragment

Auto-Refresh:
  Jobs table has hx-trigger="every 10s"
  → hx-get="/api/dashboard?tab=jobs&fragment=jobs-table"
  → hx-target="#jobs-table"
  → Server returns: just the <tbody> rows
```

---

## Tab Structure & Pages

### Tab 1: PLATFORM (Priority 1)

The primary operational interface for the platform integration layer.

| Sub-Tab | Purpose | Key Endpoints |
|---------|---------|---------------|
| **Submit** | Unified submit form (raster/vector/zarr) | `POST /api/platform/submit` |
| **Requests** | List & filter platform requests | `GET /api/platform/status` |
| **Request Detail** | Full request lifecycle view | `GET /api/platform/status/{id}` |
| **Approvals** | Approval queue with approve/reject/revoke actions | `GET /api/platform/approvals`, `POST /api/platform/approve` |
| **Catalog** | Lookup by DDH identifiers, browse assets | `GET /api/platform/catalog/*` |
| **Lineage** | Data lineage trace for a request | `GET /api/platform/lineage/{id}` |

**Submit Sub-Tab Layout:**
```
┌─────────────────────────────────────────────────┐
│ SUBMIT DATA                                     │
├─────────────────────────────────────────────────┤
│                                                 │
│  Data Type:  (•) Raster  ( ) Vector  ( ) Zarr  │
│                                                 │
│  ┌─ DDH Identifiers ──────────────────────┐    │
│  │ Dataset ID:   [________________]       │    │
│  │ Resource ID:  [________________]       │    │
│  │ Version ID:   [________________]       │    │
│  └────────────────────────────────────────┘    │
│                                                 │
│  ┌─ File Source ──────────────────────────┐    │
│  │ Blob Path:    [________________] [Browse]│   │
│  │ Container:    (•) bronze  ( ) custom   │    │
│  └────────────────────────────────────────┘    │
│                                                 │
│  ┌─ Processing Options ──────── [▼ expand] ┐   │
│  │ (hidden by default, expand for power    │   │
│  │  users: table_name, collection_id,      │   │
│  │  processing_mode, etc.)                 │   │
│  └────────────────────────────────────────┘    │
│                                                 │
│  [ Validate (dry run) ]   [ Submit ]            │
│                                                 │
│  ┌─ Result ───────────────────────────────┐    │
│  │ Request ID: req-abc123                 │    │
│  │ Job ID: job-def456                     │    │
│  │ Status: PROCESSING ◉                  │    │
│  │ [View Request →]                       │    │
│  └────────────────────────────────────────┘    │
└─────────────────────────────────────────────────┘
```

**Requests Sub-Tab Layout:**
```
┌─────────────────────────────────────────────────────────────┐
│ PLATFORM REQUESTS                                           │
├─────────────────────────────────────────────────────────────┤
│ Filter: [All ▼] [Last 24h ▼] [Search ID...]  [⟳ Refresh]  │
├─────────────────────────────────────────────────────────────┤
│ ┌──────────────────────────────────────────────────────┐   │
│ │  5 processing  │  12 completed  │  2 failed  │  3 pending │
│ └──────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│ Request ID  │ Data Type │ Dataset    │ Status     │ Age     │
│─────────────┼───────────┼────────────┼────────────┼─────────│
│ req-abc123  │ raster    │ ds-flood   │ ◉ PROC     │ 3m      │
│ req-def456  │ vector    │ ds-wells   │ ✓ DONE     │ 12m     │
│ req-ghi789  │ zarr      │ ds-climate │ ✗ FAIL     │ 1h      │
│ req-jkl012  │ raster    │ ds-dem     │ ◎ PENDING  │ 2h      │
└─────────────────────────────────────────────────────────────┘
```

**Approvals Sub-Tab Layout:**
```
┌─────────────────────────────────────────────────────────────┐
│ APPROVAL QUEUE                          [5 pending review]  │
├─────────────────────────────────────────────────────────────┤
│ Filter: [Pending ▼] [All Types ▼]                          │
├─────────────────────────────────────────────────────────────┤
│ Release         │ Asset          │ Type   │ Clearance │ Act │
│─────────────────┼────────────────┼────────┼───────────┼─────│
│ rel-abc (v1)    │ ds-flood/r-01  │ raster │ OUO       │ [✓][✗]│
│ rel-def (v2)    │ ds-wells/r-03  │ vector │ OUO       │ [✓][✗]│
│ rel-ghi (v1)    │ ds-dem/r-01    │ raster │ PUBLIC    │ [✓][✗]│
└─────────────────────────────────────────────────────────────┘
│                                                             │
│ ┌─ Approval Detail (expand on row click) ────────────┐    │
│ │ Release: rel-abc-1234-5678-9012                     │    │
│ │ Asset: ds-flood / r-01 (v1, ord1)                   │    │
│ │ Job: job-xyz → COMPLETED 01 MAR 2026                │    │
│ │ STAC: flood-data-ord1 in collection flood-data      │    │
│ │ Blob: silver/raster/flood-data-ord1.tif             │    │
│ │                                                     │    │
│ │ Clearance: [OUO ▼]  Reviewer: [________]           │    │
│ │ [ Approve ]  [ Reject ]  Reason: [________]         │    │
│ └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### Tab 2: JOBS (Priority 2)

Operational monitoring for all processing jobs.

| Sub-Tab | Purpose | Key Endpoints |
|---------|---------|---------------|
| **Monitor** | Live job table with auto-refresh | `GET /api/dbadmin/jobs` |
| **Tasks** | Task-level drill-down for a job | `GET /api/dbadmin/tasks/{job_id}` |
| **Pipeline** | Stage visualization for active jobs | `GET /api/jobs/status/{job_id}` |
| **Failures** | Recent failures with error summaries | `GET /api/platform/failures` |

**Monitor Sub-Tab Layout:**
```
┌─────────────────────────────────────────────────────────────┐
│ JOB MONITOR                                    ⟳ auto 10s   │
├─────────────────────────────────────────────────────────────┤
│ ┌──────────────────────────────────────────────────────┐   │
│ │  3 processing  │  47 completed  │  2 failed │ 1 queued │  │
│ └──────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│ Filter: [All ▼]  [Last 24h ▼]  [Type ▼]  [Search...]      │
├─────────────────────────────────────────────────────────────┤
│ Job ID   │ Type           │ Status  │ Stage │ Tasks │ Age   │
│──────────┼────────────────┼─────────┼───────┼───────┼───────│
│ job-abc  │ process_raster │ ◉ PROC  │ 2/3   │ 4/6   │ 5m    │
│ job-def  │ process_vector │ ✓ DONE  │ 3/3   │ 3/3   │ 12m   │
│ job-ghi  │ virtualzarr    │ ✗ FAIL  │ 3/5   │ 8/12  │ 1h    │
├─────────────────────────────────────────────────────────────┤
│ ┌─ Job Detail (expand on row click) ─────────────────┐    │
│ │ Job: job-abc-1234-5678                              │    │
│ │ Type: process_raster_v2                             │    │
│ │ Submitted: 01 MAR 2026 14:30:00                     │    │
│ │                                                     │    │
│ │ Stage 1: download    [████████████] 2/2 ✓           │    │
│ │ Stage 2: process     [██████░░░░░░] 3/5 ◉           │    │
│ │ Stage 3: register    [░░░░░░░░░░░░] 0/1 ◎           │    │
│ │                                                     │    │
│ │ [View Tasks →] [View Lineage →] [View Logs →]      │    │
│ └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### Tab 3: DATA (Priority 3)

Browse and inspect processed data assets.

| Sub-Tab | Purpose | Key Endpoints |
|---------|---------|---------------|
| **Assets** | Asset inventory with release history | `GET /api/platform/catalog/dataset/{id}` |
| **STAC** | STAC collections and items | `GET /api/stac/collections` |
| **Vector** | OGC Features collections | `GET /api/features/collections` |
| **Storage** | Blob storage browser | Internal storage API |

### Tab 4: SYSTEM (Priority 4)

System health and administrative tools.

| Sub-Tab | Purpose | Key Endpoints |
|---------|---------|---------------|
| **Health** | Cross-system health dashboard | `/health`, `/system-health`, `/api/platform/health` |
| **Database** | Schema stats, slow queries, connections | `GET /api/dbadmin/diagnostics`, `/api/dbadmin/health` |
| **Queues** | Service Bus queue monitoring | Internal queue stats |
| **Maintenance** | Schema ensure/rebuild, cleanup | `POST /api/dbadmin/maintenance` |

---

## Style Scheme Variants

The dashboard needs a visual identity. Below are **4 style scheme variants** for comparison. The GREENFIELD agents should evaluate each and the Mediator should select or synthesize the final scheme.

### Variant 1: "Current Interface" (Baseline)

The existing `web_interfaces/` design system. Government/enterprise blue.

| Token | Value | Notes |
|-------|-------|-------|
| **Primary** | `#0071BC` | Links, buttons, primary actions |
| **Primary Dark** | `#245AAD` | Hover states |
| **Navy** | `#053657` | Headings, main text |
| **Cyan** | `#00A3DA` | Hover accents |
| **Gold** | `#FFC14D` | Highlights, "latest" badges |
| **Gray** | `#626F86` | Secondary text |
| **Gray Light** | `#e9ecef` | Borders, dividers |
| **Background** | `#f8f9fa` | Page background |
| **Font** | "Open Sans", Arial, sans-serif | Clean sans-serif |
| **Font Mono** | Monaco, Courier New, monospace | Code/IDs |
| **Base Size** | 14px | Body text |
| **Border Radius** | 8px cards, 3px buttons, 12px badges | Soft roundness |
| **Shadows** | `0 1px 3px rgba(0,0,0,0.1)` | Subtle elevation |

**Status Badges:**

| Status | Background | Text |
|--------|-----------|------|
| Queued | `#f3f4f6` | `#6b7280` |
| Pending | `#fef3c7` | `#d97706` |
| Processing | `#dbeafe` | `#0071BC` |
| Completed | `#d1fae5` | `#059669` |
| Failed | `#fee2e2` | `#dc2626` |

**Vibe**: Professional, government-adjacent, safe. Reads "enterprise software."

---

### Variant 2: "Dark Operator"

Dark-background ops dashboard. Inspired by Grafana, Datadog, Arc browser dark mode.

| Token | Value | Notes |
|-------|-------|-------|
| **Primary** | `#6366F1` | Indigo — actions, active tabs |
| **Primary Light** | `#818CF8` | Hover states |
| **Accent Green** | `#34D399` | Success, healthy, completed |
| **Accent Amber** | `#FBBF24` | Warnings, in-progress |
| **Accent Red** | `#F87171` | Errors, failures |
| **Text Primary** | `#F1F5F9` | Main text (light on dark) |
| **Text Secondary** | `#94A3B8` | Labels, metadata |
| **Surface** | `#1E293B` | Cards, panels |
| **Background** | `#0F172A` | Page background (slate-900) |
| **Border** | `#334155` | Subtle borders |
| **Font** | "Inter", "SF Pro", system-ui, sans-serif | Modern, tight |
| **Font Mono** | "JetBrains Mono", "Fira Code", monospace | Developer-grade |
| **Base Size** | 13px | Denser information |
| **Border Radius** | 6px cards, 4px buttons, 10px badges | Slightly tighter |
| **Shadows** | `0 1px 3px rgba(0,0,0,0.3)` | Deeper on dark |

**Status Badges:**

| Status | Background | Text |
|--------|-----------|------|
| Queued | `#1E293B` | `#94A3B8` |
| Pending | `#422006` | `#FBBF24` |
| Processing | `#1E1B4B` | `#818CF8` |
| Completed | `#052E16` | `#34D399` |
| Failed | `#450A0A` | `#F87171` |

**Vibe**: Modern ops center. Dense, high-contrast, looks like you're running infrastructure.

---

### Variant 3: "Nordic Minimal"

Light background, muted palette, generous whitespace. Inspired by Linear, Vercel, Notion.

| Token | Value | Notes |
|-------|-------|-------|
| **Primary** | `#18181B` | Near-black — buttons, headings |
| **Primary Hover** | `#3F3F46` | Subtle hover |
| **Accent Blue** | `#3B82F6` | Links, active states |
| **Accent Green** | `#22C55E` | Success |
| **Accent Amber** | `#EAB308` | Warnings |
| **Accent Red** | `#EF4444` | Errors |
| **Text Primary** | `#18181B` | Main text (near-black) |
| **Text Secondary** | `#71717A` | Labels, secondary (zinc-500) |
| **Surface** | `#FFFFFF` | Cards (pure white) |
| **Background** | `#FAFAFA` | Page background (zinc-50) |
| **Border** | `#E4E4E7` | Very subtle borders (zinc-200) |
| **Font** | "Inter", system-ui, sans-serif | Clean geometric |
| **Font Mono** | "SF Mono", "Cascadia Code", monospace | Crisp |
| **Base Size** | 14px | Standard |
| **Border Radius** | 8px cards, 6px buttons, 999px badges (pill) | Rounded, modern |
| **Shadows** | `0 1px 2px rgba(0,0,0,0.05)` | Almost none |

**Status Badges (pill-shaped):**

| Status | Background | Text |
|--------|-----------|------|
| Queued | `#F4F4F5` | `#71717A` |
| Pending | `#FEF9C3` | `#A16207` |
| Processing | `#DBEAFE` | `#1D4ED8` |
| Completed | `#DCFCE7` | `#15803D` |
| Failed | `#FEE2E2` | `#B91C1C` |

**Vibe**: Calm, focused, typography-driven. Reads "modern SaaS tool."

---

### Variant 4: "Geo Cartographic"

Earthy tones inspired by cartography and geospatial tooling. Nods to the domain.

| Token | Value | Notes |
|-------|-------|-------|
| **Primary** | `#1B4332` | Deep forest green — headings, primary |
| **Primary Light** | `#2D6A4F` | Hover states |
| **Accent Teal** | `#0D9488` | Links, active elements |
| **Accent Amber** | `#D97706` | Warnings, pending |
| **Accent Red** | `#DC2626` | Errors |
| **Accent Sand** | `#D4A574` | Highlights, accents |
| **Text Primary** | `#1C1917` | Main text (stone-900) |
| **Text Secondary** | `#78716C` | Labels (stone-500) |
| **Surface** | `#FFFBF5` | Cards (warm white) |
| **Background** | `#FAF5EF` | Page background (warm cream) |
| **Border** | `#D6D3D1` | Warm gray borders (stone-300) |
| **Font** | "Source Sans 3", "Noto Sans", sans-serif | Readable, neutral |
| **Font Mono** | "Source Code Pro", monospace | Matching family |
| **Base Size** | 14px | Standard |
| **Border Radius** | 4px cards, 3px buttons, 12px badges | Slightly sharper |
| **Shadows** | `0 1px 3px rgba(28,25,23,0.08)` | Warm shadow |

**Status Badges:**

| Status | Background | Text |
|--------|-----------|------|
| Queued | `#F5F5F4` | `#78716C` |
| Pending | `#FEF3C7` | `#92400E` |
| Processing | `#CCFBF1` | `#0F766E` |
| Completed | `#D1FAE5` | `#065F46` |
| Failed | `#FEE2E2` | `#991B1B` |

**Vibe**: Warm, domain-aware, feels like a GIS professional tool. Unique identity.

---

### Variant Comparison Matrix

| Attribute | V1 Current | V2 Dark Operator | V3 Nordic | V4 Geo Carto |
|-----------|-----------|------------------|-----------|--------------|
| Background | Light gray | Dark slate | Near-white | Warm cream |
| Primary action | Blue | Indigo | Black | Forest green |
| Information density | Medium | High | Medium | Medium |
| Eye strain (long sessions) | Low | Medium* | Low | Low |
| Distinctiveness | Low (generic) | High | Medium | High |
| Domain fit | Neutral | Ops/infra | SaaS/modern | Geospatial |
| Font vibe | Professional | Developer | Minimal | Academic |

*Dark mode reduces eye strain in low-light but can increase it in bright rooms.

**Agent instruction**: The Advocate should design for one variant, the Critic should challenge the choice, and the Mediator should make the final call (or synthesize). The user wants agent-driven design choice.

---

## Data Flow & HTMX Patterns

### Pattern 1: Tab Navigation

```html
<!-- Top tab bar -->
<nav id="tab-bar">
  <a hx-get="/api/dashboard?tab=platform"
     hx-target="#main-content"
     hx-push-url="true"
     class="tab active">Platform</a>
  <a hx-get="/api/dashboard?tab=jobs"
     hx-target="#main-content"
     hx-push-url="true"
     class="tab">Jobs</a>
  <!-- ... -->
</nav>

<!-- Content area swapped by HTMX -->
<div id="main-content">
  <!-- Panel HTML injected here -->
</div>
```

### Pattern 2: Sub-Tab Within Panel

```html
<!-- Sub-tabs rendered by the panel -->
<div id="sub-tabs">
  <a hx-get="/api/dashboard?tab=platform&section=submit"
     hx-target="#panel-content"
     class="sub-tab active">Submit</a>
  <a hx-get="/api/dashboard?tab=platform&section=requests"
     hx-target="#panel-content"
     class="sub-tab">Requests</a>
</div>

<div id="panel-content">
  <!-- Section HTML injected here -->
</div>
```

### Pattern 3: Auto-Refresh Table

```html
<!-- Jobs table that auto-refreshes every 10s -->
<div hx-get="/api/dashboard?tab=jobs&fragment=jobs-table"
     hx-trigger="every 10s"
     hx-target="this"
     hx-swap="innerHTML">
  <table>
    <tbody id="jobs-tbody">
      <!-- Rows refreshed automatically -->
    </tbody>
  </table>
</div>
```

### Pattern 4: Inline Actions (Approve/Reject)

```html
<!-- Approve button triggers POST, replaces row -->
<button hx-post="/api/platform/approve"
        hx-vals='{"release_id": "rel-abc", "reviewer": "operator"}'
        hx-target="#row-rel-abc"
        hx-swap="outerHTML"
        hx-confirm="Approve release rel-abc for publication?">
  ✓ Approve
</button>
```

### Pattern 5: Expandable Row Detail

```html
<!-- Click row to load detail fragment -->
<tr hx-get="/api/dashboard?tab=jobs&fragment=job-detail&job_id=abc123"
    hx-target="#detail-panel"
    hx-swap="innerHTML"
    class="clickable-row">
  <td>job-abc123</td>
  <td>process_raster_v2</td>
  <td><span class="badge processing">Processing</span></td>
</tr>

<!-- Detail panel appears below table -->
<div id="detail-panel"></div>
```

---

## API Endpoints Referenced

### Platform (Tab 1) — 17 Endpoints

| Endpoint | Method | Dashboard Usage |
|----------|--------|----------------|
| `/api/platform/submit` | POST | Submit form |
| `/api/platform/validate` | POST | Dry-run validation |
| `/api/platform/status` | GET | Request list |
| `/api/platform/status/{id}` | GET | Request detail |
| `/api/platform/health` | GET | Platform health card |
| `/api/platform/failures` | GET | Failures sub-tab |
| `/api/platform/lineage/{id}` | GET | Lineage view |
| `/api/platform/approve` | POST | Approve action |
| `/api/platform/reject` | POST | Reject action |
| `/api/platform/revoke` | POST | Revoke action |
| `/api/platform/approvals` | GET | Approval queue list |
| `/api/platform/approvals/{id}` | GET | Approval detail |
| `/api/platform/approvals/status` | GET | Batch status lookup |
| `/api/platform/catalog/lookup` | GET | Catalog search |
| `/api/platform/catalog/asset/{id}` | GET | Asset detail |
| `/api/platform/catalog/dataset/{id}` | GET | Dataset listing |
| `/api/platform/catalog/item/{c}/{i}` | GET | STAC item view |

### Jobs (Tab 2) — 7 Endpoints

| Endpoint | Method | Dashboard Usage |
|----------|--------|----------------|
| `/api/dbadmin/jobs` | GET | Job list with filters |
| `/api/dbadmin/jobs/{id}` | GET | Job detail |
| `/api/dbadmin/tasks/{job_id}` | GET | Task drill-down |
| `/api/jobs/status/{job_id}` | GET | Stage visualization |
| `/api/platform/failures` | GET | Failure analysis |
| `/api/jobs/events/{job_id}` | GET | Event timeline |
| `/api/jobs/logs/{job_id}` | GET | Job logs |

### Data (Tab 3) — 8 Endpoints

| Endpoint | Method | Dashboard Usage |
|----------|--------|----------------|
| `/api/stac/collections` | GET | STAC collection list |
| `/api/stac/collections/{id}` | GET | Collection detail |
| `/api/stac/collections/{id}/items` | GET | Item browse |
| `/api/features/collections` | GET | Vector collection list |
| `/api/assets/pending-review` | GET | Pending assets |
| `/api/assets/approval-stats` | GET | Approval counts |
| `/api/assets/{id}/approval` | GET | Asset approval state |
| Internal blob listing | — | Storage browser |

### System (Tab 4) — 10 Endpoints

| Endpoint | Method | Dashboard Usage |
|----------|--------|----------------|
| `/health` | GET | Liveness |
| `/system-health` | GET | Detailed health |
| `/api/platform/health` | GET | Platform readiness |
| `/api/dbadmin/health` | GET | DB health |
| `/api/dbadmin/health/performance` | GET | DB performance |
| `/api/dbadmin/diagnostics` | GET | Full diagnostics |
| `/api/dbadmin/activity` | GET | Active queries |
| `/api/dbadmin/schemas` | GET | Schema stats |
| `/api/stac/health` | GET | STAC health |
| `/api/dbadmin/maintenance` | POST | Schema operations |

---

## Success Criteria

### Must Have (MVP)

1. Dashboard shell renders at `/api/dashboard` with 4 working tabs
2. Platform tab: submit form posts to `/api/platform/submit` and shows result
3. Platform tab: request list loads from `/api/platform/status` with status filtering
4. Platform tab: approval queue with inline approve/reject actions
5. Jobs tab: live job table with auto-refresh and status filters
6. Jobs tab: click-to-expand job detail with stage progress bars
7. Tab switching via HTMX (no full page reload)
8. Consistent design system across all panels
9. Old `/api/interface/*` routes still work

### Should Have (Post-MVP)

10. Platform tab: catalog lookup and lineage view
11. Data tab: STAC collection browser
12. Data tab: vector collection browser
13. System tab: health dashboard with component cards
14. System tab: database stats and diagnostics
15. Sub-tab memory (remembers last sub-tab per tab via URL)

### Nice to Have (Future)

16. System tab: schema maintenance actions (ensure/rebuild with confirmation)
17. Keyboard shortcuts (j/k navigation, Enter to expand, Esc to close)
18. Export table data as CSV
19. Dark/light mode toggle (if multiple variants implemented)

---

## Open Questions

These should be resolved by the GREENFIELD agents (Advocate, Critic, Operator):

1. **Style Variant Selection**: Which of the 4 variants (or synthesis) best serves the operator use case?
2. **HTMX Version**: Pin to HTMX 1.9.x (stable) or use 2.0? (CDN-served either way)
3. **Font Loading**: Self-host fonts (reliability) or use Google Fonts CDN (simplicity)?
4. **Tab State Persistence**: URL-only (stateless) or add `hx-push-url` for browser back/forward?
5. **Error Handling UX**: Toast notifications, inline alerts, or dedicated error panel?
6. **Mobile Breakpoint**: What's the minimum supported width? (Suggestion: 768px tablet minimum)
7. **Pagination Model**: Offset-based (`?page=2&limit=25`) or cursor-based for large result sets?

---

## GREENFIELD Agent Dispatch Instructions

### Tier 1 Briefing (for Spec Writer → A + C + O)

Use this document as the Tier 1 system context. The spec should formalize:
- PURPOSE: Unified operator dashboard for the GeoAPI platform
- BOUNDARIES: What it does (UI) vs. what it doesn't (no new API endpoints, no data processing)
- CONTRACTS: Route pattern, HTMX protocol, panel interface
- INVARIANTS: Old routes preserved, zero build step, Azure Function compatible
- NON-FUNCTIONAL: Sub-second tab switching, < 100KB per panel, auto-refresh

### Tier 2 Briefing (held until Mediator + Builder)

- Registry pattern (PanelRegistry matching InterfaceRegistry)
- Military date format everywhere
- File headers per project convention
- No backward compatibility shims
- Error handling: contract violations bubble up, business errors handled gracefully
- Status badge colors must match job/approval state semantics

### Style Variant Instruction

The Advocate should champion their preferred variant with rationale. The Critic should attack the choice. The Operator should assess practical implications (font loading, dark mode contrast ratios, WCAG compliance). The Mediator resolves with the final scheme.

---

## References

| Document | Relevance |
|----------|-----------|
| `docs/agent_review/agents/GREENFIELD_AGENT.md` | Pipeline definition |
| `web_interfaces/base.py` | Current design system CSS (Variant 1 source) |
| `web_interfaces/__init__.py` | Registry pattern to mirror |
| `docs_claude/ARCHITECTURE_REFERENCE.md` | API architecture |
| `docs_claude/CLAUDE_CONTEXT.md` | Full system context |

---

*Document created for GREENFIELD pipeline dispatch. Style variants are intentionally left as options for agent-driven design selection.*
