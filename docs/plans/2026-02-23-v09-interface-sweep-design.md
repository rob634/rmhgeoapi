# V0.9 Interface Sweep — Design Document

**Date**: 23 FEB 2026
**Status**: APPROVED
**Version**: 0.9.0.0

---

## Summary

Update all web interface pages to use V0.9 Asset/Release patterns, and build a new Asset Versions visualization page. The V0.9 entity split (Asset = stable identity, AssetRelease = versioned lifecycle) is fully implemented in the backend and status endpoint — the UI needs to catch up.

## Approach: Pattern-First, Then Pages

1. Build shared V0.9 UI components (badges, chips, headers) in `base.py`
2. Build new Asset Versions page using those components
3. Sweep existing pages (STAC, Jobs, Home, Platform) adding V0.9 awareness

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Audience | Both reviewers and submitters | Full lifecycle view |
| Scope | Full V0.9 interface sweep | All pages need updating |
| Layout | Table with expandable rows | Dense, data-focused |
| Data source | Existing status endpoint | No new backend needed |
| Execution | Pattern-first shared components | DRY, consistent |

---

## Part 1: Shared V0.9 UI Components

**Location**: `web_interfaces/base.py` (extend COMMON_CSS + add helper functions)

### 1.1 Status Badges (CSS)

| Badge Type | States | Colors |
|-----------|--------|--------|
| Approval | `pending_review` (amber), `approved` (green), `rejected` (red), `revoked` (gray) |
| Clearance | `uncleared` (gray), `ouo` (amber), `public` (green) |
| Processing | `pending` (gray), `processing` (blue), `completed` (green), `failed` (red) |
| Version chip | `v1`/`v2` (navy pill), `(draft)` (dashed border), star icon for `is_latest` |

### 1.2 Python Helper Functions

```python
def render_approval_badge(state: str) -> str
def render_clearance_badge(state: str) -> str
def render_processing_badge(status: str) -> str
def render_version_chip(version_id: str | None, ordinal: int, is_latest: bool) -> str
def render_asset_header(asset: dict) -> str
```

Pure HTML-returning functions. No JavaScript required.

---

## Part 2: New Asset Versions Page

**Route**: `/api/interface/asset-versions?asset_id={asset_id}`
**Alt entry**: `/api/interface/asset-versions?dataset_id=X&resource_id=Y`

### 2.1 Layout

```
┌─────────────────────────────────────────────────────────┐
│  NavBar (shared)                                        │
├─────────────────────────────────────────────────────────┤
│  Asset Header                                           │
│  floods/jakarta (raster) | asset_id: 05cb99e1...       │
│  3 releases | Created: 15 FEB 2026                     │
├─────────────────────────────────────────────────────────┤
│  Release Table                                          │
│ ┌─────┬─────────┬───────────┬──────────┬────────┬─────┐│
│ │ Ord │ Version │ Process   │ Approval │ Clear  │  ⋮  ││
│ ├─────┼─────────┼───────────┼──────────┼────────┼─────┤│
│ │  3  │ (draft) │ running   │ pending  │ —      │ [▶] ││
│ │  2  │ v2 ★    │ done      │ approved │ public │ [▶] ││
│ │  1  │ v1      │ done      │ approved │ ouo    │ [▶] ││
│ └─────┴─────────┴───────────┴──────────┴────────┴─────┘│
│                                                         │
│  ▼ Expanded: v2 (release_id: 2c4d935a...)              │
│  ┌─────────────────────────────────────────────────┐   │
│  │ Outputs: blob_path, stac_item, stac_collection  │   │
│  │ Actions: [Preview] [Viewer] [STAC] [Revoke]     │   │
│  │ Timestamps: submitted, approved, reviewer        │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### 2.2 Data Source

Calls `/api/platform/status/{asset_id}` from JavaScript on page load. Uses:
- `asset` block → header
- `versions` array → table rows
- `services` block → action links
- `approval` block → reviewer actions

### 2.3 Context-Aware Actions

| Release State | Available Actions |
|---------------|------------------|
| `pending_review` + `completed` | Approve, Reject, Preview |
| `approved` | Revoke, View in STAC, Preview |
| `rejected` | Read-only (show reason) |
| `processing` | Read-only (show progress) |
| `failed` | Read-only (show error) |

### 2.4 Expand/Collapse

Pure JS click handler on table rows. Expanded section shows:
- Physical outputs (blob_path, table_name, stac_item_id)
- Action buttons (linked to raster-viewer, STAC, or calling approval endpoints)
- Timestamps and audit info (reviewer, reviewed_at)
- Release ID (truncated with copy button)

---

## Part 3: Existing Page Updates

### 3.1 STAC Interface (HIGH priority)

**Problem**: Uses V0.8 approval lookup `/api/platform/approvals/status?stac_collection_ids=`.

**Changes**:
- Replace approval lookup with `/api/assets/approval-stats` for dashboard counts
- Add "Versions" link on each collection card → Asset Versions page
- Use shared `render_approval_badge()` on cards
- Add `version_ordinal` column in items table

### 3.2 Jobs Interface (MEDIUM priority)

**Problem**: No association between jobs and assets/releases.

**Changes**:
- Add `Asset` and `Version` columns to jobs table
- Link from asset column → Asset Versions page
- Use shared `render_version_chip()` for version display
- Source: resolve job_id → release via status endpoint or direct DB query

### 3.3 Home Interface (LOW priority)

**Changes**:
- Add "Approval Queue" card showing pending_review count
- Link to approval workflow / Asset Versions page
- Add "Recent Releases" quick link

### 3.4 Platform Interface (LOW priority)

**Changes**:
- Add approval state summary counts
- Link to Asset Versions page for drill-down

---

## Implementation Order

1. Shared V0.9 CSS badges + Python helpers in `base.py`
2. New `web_interfaces/asset_versions/` page
3. STAC interface V0.9 refactor
4. Jobs interface release columns
5. Home dashboard approval queue
6. Platform interface summary

Each step is a discrete, testable commit.

---

## Out of Scope

- New backend endpoints (uses existing status + approval APIs)
- HTMX dynamic refresh (future enhancement)
- Mobile-specific layouts
- Raster viewer updates (already ~95% V0.9 ready)
- Submit interface updates (already ~70% V0.9 ready)
