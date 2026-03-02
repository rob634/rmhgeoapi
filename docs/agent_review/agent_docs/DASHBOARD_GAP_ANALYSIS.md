# Dashboard Gap Analysis: Spec vs Build

**Date**: 02 MAR 2026
**Updated**: 02 MAR 2026 — Session 1 fixes applied, false positives corrected
**Source**: GREENFIELD Run 19 (Platform Dashboard)
**Scope**: All gaps between Mediator Resolved Spec (M) and Builder output (B)

---

## Overview

GREENFIELD Run 19 produced a 4-tab, 18-sub-tab dashboard in 9 files (4,499 lines). The design pipeline (S → A → C → O → M) produced a thorough spec. The Builder (B) implemented the architecture correctly but ran out of output budget on complex "write" interfaces, producing stubs where the spec defined detailed forms.

This document catalogs every gap, classifies root cause, and provides a high-level implementation plan for each.

---

## Gap Classification

| Code | Root Cause | Description |
|------|-----------|-------------|
| **BUD** | Budget collapse | Builder ran out of output capacity; later components got stubs |
| **BUG** | Implementation bug | Code was written but has a defect |
| **SIMP** | Intentional simplification | Builder chose a simpler approach than spec'd |
| **DEF** | Deferred by spec | Mediator explicitly deferred this to post-MVP |

---

## MAJOR GAPS

### GAP-1: Submit Form is a Stub (BUD)

**Spec says**: Unified multi-step form with data type radio selector, DDH identifier fields (dataset_id, resource_id, version_id), blob path with Browse button, container selector (bronze/custom), collapsible processing options section, validate + submit buttons, structured result card with "View Request" link.

**Built**: Generic form with job type dropdown, plain text "Source URL" input, dataset_id only, clearance dropdown, JSON textarea for extra params, validate + submit buttons.

**What's missing**:
- Data type radio buttons with conditional field toggling
- Resource ID and Version ID fields
- Blob path browser (container → file list → click to select)
- Container selector
- Processing options (raster_type, output_tier, input_crs for raster; table_name, layer_name, lat/lon/wkt columns for vector)
- Raster collection mode (multi-file select, file count/size display)
- Structured result card with Request ID, Job ID, Status, "View Request" link
- Client-side form validation (DDH ID pattern check)
- Live cURL generation (old interface feature, not in GREENFIELD spec but high-value)

**Files affected**: `web_dashboard/panels/platform.py` — `_render_submit()` method

**Implementation plan**:
1. Replace `_render_submit()` with multi-section form (~250 lines)
2. Add data type radio buttons with JS toggle for type-specific field sections
3. Add all DDH identifier fields (dataset_id, resource_id, version_id, previous_version_id)
4. Add file source section with container dropdown (HTMX-populated via fragment)
5. Add collapsible processing options with type-specific fields
6. Add `_fragment_containers()` and `_fragment_files()` methods for file browser
7. Add `_fragment_validate()` method for inline validation result display
8. Add structured result card template for submit success
9. Wire new fragments into `render_fragment()` dispatch

**Estimated scope**: ~400 lines new/modified in `platform.py`, ~50 lines in `__init__.py` for new fragment dispatch

**Priority**: P0 — This is the primary "write" interface. Without it, operators must use cURL or the old `/api/interface/submit`.

---

### GAP-2: Request Detail Fragment Not Wired (BUG)

**Spec says**: Row click on Requests table expands detail below table showing full request info with "View Job" and "View Lineage" links.

**Built**: `_fragment_request_detail()` method exists and builds the detail card correctly. But the fragment name is not registered in `render_fragment()` dispatch, so row clicks produce silent errors.

**What's missing**:
- Fragment name wiring in `render_fragment()` method
- "View Job" link (navigates to Jobs/Tasks with job_id)
- "View Lineage" link (navigates to Platform/Lineage with request_id)

**Files affected**: `web_dashboard/panels/platform.py` — `render_fragment()` method

**Implementation plan**:
1. Add `"request-detail"` case to `render_fragment()` dispatch
2. Add "View Job" and "View Lineage" HTMX links to the detail card
3. Verify `#detail-panel` target div exists in `_render_requests()`

**Estimated scope**: ~15 lines modified in `platform.py`

**Priority**: P0 — Dead feature on arrival. Trivial fix.

---

### GAP-3: Approval Detail Form Missing (BUD/SIMP)

**Spec says**: Row click expands approval detail showing release info, STAC item, blob path. Detail includes clearance dropdown and reviewer name input. Approve/Reject buttons are in the expanded detail, not on the table row.

**Built**: Approve/Reject buttons are directly on table rows. `_fragment_approval_detail()` exists but only shows read-only release info. No clearance dropdown or reviewer input in the detail. Buttons send only `release_id` without clearance or reviewer fields.

**What's missing**:
- Clearance dropdown in approval detail card
- Reviewer name text input
- Move Approve/Reject buttons from table row into detail card
- Pass clearance + reviewer in `hx-vals` on button click
- STAC item reference and blob path in detail view

**Files affected**: `web_dashboard/panels/platform.py` — `_render_approvals()` and `_fragment_approval_detail()`

**Implementation plan**:
1. Simplify table row actions to just a "Review" button that loads detail
2. Move Approve/Reject/Revoke buttons into `_fragment_approval_detail()`
3. Add clearance dropdown and reviewer input to detail card
4. Add `hx-include` or `hx-vals` to pass form fields with action buttons
5. Show STAC item reference and blob path from release data

**Estimated scope**: ~80 lines modified in `platform.py`

**Priority**: P1 — Approvals work functionally but operators can't set clearance or record reviewer. Data quality concern.

---

### GAP-4: Health Endpoint Paths Wrong (BUG)

**Spec says**: Health checks at `/api/health`, `/api/system-health`, `/api/platform/health`, `/api/dbadmin/health`, `/api/stac/health`.

**Built**: System panel calls `/health` and `/system-health` without `/api/` prefix. These paths return 404 on Azure Functions, so health cards always show errors.

**What's missing**:
- Correct `/api/` prefix on health endpoint paths

**Files affected**: `web_dashboard/panels/system.py` — `_build_health_cards()`

**Implementation plan**:
1. Fix endpoint paths to include `/api/` prefix
2. Verify all 5 health endpoints are correct

**Estimated scope**: ~2 lines changed in `system.py`

**Priority**: P0 — Health cards are broken. Trivial fix.

---

### GAP-5: Bottom Status Bar Not Built (SIMP)

**Spec says**: Dark ops-colored bar (`#1a1a2e`) at bottom of dashboard. Persistent across all tabs. Shows: active job count, DB connection status, last refresh timestamp, app version.

**Built**: Not implemented. Version is shown in the header only.

**What's missing**:
- Status bar HTML in `shell.py`
- CSS for dark status bar
- JS to populate active job count (from Jobs monitor auto-refresh)
- Last refresh timestamp update on any HTMX swap
- DB connection status indicator

**Files affected**: `web_dashboard/shell.py`

**Implementation plan**:
1. Add `<footer id="status-bar">` to shell HTML
2. Add CSS: fixed bottom, dark background, flex layout
3. Add static content: version (from config), environment
4. Add dynamic content via HTMX OOB swap: active job count updated when Jobs tab refreshes
5. Add JS timestamp update on `htmx:afterSwap` event

**Estimated scope**: ~60 lines in `shell.py`

**Priority**: P2 — Cosmetic/informational. Nice to have but not blocking any workflow.

---

## MODERATE GAPS

### GAP-6: Job Monitor Missing Type Filter and Search (BUD)

**Spec says**: Job monitor has status filter, time range filter, job type filter, and full-text search by job ID.

**Built**: Only status filter and time range filter. No job type dropdown, no search input.

**What's missing**:
- Job type dropdown filter (populated from known job types or API response)
- Job ID search input with `hx-trigger="keyup changed delay:500ms"`
- Include both in `hx-include` for auto-refresh persistence

**Files affected**: `web_dashboard/panels/jobs.py` — `_render_monitor()`

**Implementation plan**:
1. Add job type select filter to filter bar
2. Add job ID search input to filter bar
3. Pass both as query params in fragment requests
4. Ensure auto-refresh `hx-include` captures new filter inputs

**Estimated scope**: ~30 lines in `jobs.py`

**Priority**: P1 — Operators managing many job types need type filtering.

---

### GAP-7: Job Detail Missing Stage Progress Bars (BUD)

**Spec says**: Job detail (expanded on row click in Monitor) shows per-stage progress bars with width = completed/total x 100%, task counts per stage.

**Built**: Job detail card shows fields (ID, type, status, stage, created, updated, error) and "View Tasks" + "View Pipeline" links. No inline progress bars.

**What's missing**:
- Stage progress visualization in monitor detail card
- Per-stage task counts and completion percentages

**Files affected**: `web_dashboard/panels/jobs.py` — `_fragment_job_detail()`

**Implementation plan**:
1. Call `/api/jobs/status/{job_id}` in detail fragment to get stage data
2. Render progress bars (CSS width based on completion ratio)
3. Show task counts per stage: "X/Y complete, Z failed"

**Estimated scope**: ~40 lines in `jobs.py`

**Priority**: P2 — Pipeline section already has progress bars. This duplicates in the detail card for convenience.

---

### GAP-8: Maintenance Missing Cleanup Action (BUD)

**Spec says**: Three maintenance actions: Ensure (safe), Rebuild (destructive), Cleanup old jobs (partial data loss with days selector).

**Built**: Ensure and Rebuild only. No Cleanup action.

**What's missing**:
- Cleanup section with days dropdown (30, 60, 90 days)
- "Cleanup" button posting to action proxy
- Action proxy mapping for `cleanup` → `/api/dbadmin/maintenance?action=cleanup`

**Files affected**: `web_dashboard/panels/system.py` — `_render_maintenance()`, `web_dashboard/__init__.py` — action mapping

**Implementation plan**:
1. Add cleanup section to maintenance panel (dropdown + button + confirm)
2. Add `cleanup` to action endpoint mapping in `__init__.py`
3. Pass `days` parameter from form to API

**Estimated scope**: ~30 lines in `system.py`, ~5 lines in `__init__.py`

**Priority**: P2 — Useful for housekeeping but not blocking daily operations.

---

### GAP-9: Filter Selects Missing HTMX Triggers (BUG)

**Spec says**: Filter dropdowns trigger table refresh on change via HTMX.

**Built**: Filters require clicking a "Refresh" button. The `<select>` elements don't have `hx-trigger="change"` attributes.

**What's missing**:
- `hx-trigger="change"` on filter select elements
- `hx-get` and `hx-target` on filter form or individual selects
- `hx-include` to send all filter values together

**Files affected**: `web_dashboard/base_panel.py` — `filter_bar()` and `select_filter()` methods

**Implementation plan**:
1. Add `hx-trigger="change"` to `<select>` elements in `select_filter()`
2. OR add `hx-trigger="change from:select"` on the filter `<form>` wrapper
3. Ensure `hx-get`, `hx-target`, and `hx-include` are set correctly
4. Keep Refresh button as manual override

**Estimated scope**: ~15 lines in `base_panel.py`

**Priority**: P1 — Filters not auto-triggering is a UX friction point on every table.

---

### GAP-10: Action Proxy URL Injection (BUG)

**Spec says**: Action proxy translates form-encoded HTMX requests to JSON API calls.

**Built**: Action proxy concatenates `target` parameter into URL without encoding. An attacker could inject query parameters.

**What's missing**:
- URL encoding of dynamic path segments in action proxy
- Input validation on action parameters

**Files affected**: `web_dashboard/__init__.py` — `_handle_action()`

**Implementation plan**:
1. Use `urllib.parse.quote()` on any dynamic URL path segments
2. Validate `release_id`, `job_id` etc. match expected patterns (UUID/hex)

**Estimated scope**: ~10 lines in `__init__.py`

**Priority**: P1 — Security issue. Low exploit risk (internal tool) but should be fixed.

---

### GAP-11: CSS Class Label XSS Vector (BUG)

**Spec says**: All user-controlled data must be HTML-escaped.

**Built**: `stat_strip()` method injects API-controlled labels directly into CSS class attributes without escaping.

**What's missing**:
- HTML escaping of label values in `stat_strip()` CSS classes

**Files affected**: `web_dashboard/base_panel.py` — `stat_strip()`

**Implementation plan**:
1. Sanitize label values used in CSS class names (strip non-alphanumeric)
2. HTML-escape label text content (already done for display, missing for class attr)

**Estimated scope**: ~5 lines in `base_panel.py`

**Priority**: P1 — Security issue. Labels come from API responses which are generally trusted, but defense in depth.

---

## MINOR GAPS

### GAP-12: Timezone Label Incorrect (BUG)

**Spec says**: Military date format with "ET" label, server-side Eastern Time conversion.

**Built**: Label says "ET" but timestamps are displayed in UTC (no timezone conversion).

**Files affected**: `web_dashboard/base_panel.py` — `format_date()`

**Implementation plan**:
1. Either convert UTC → ET using `zoneinfo.ZoneInfo("America/New_York")`
2. Or change label from "ET" to "UTC" (simpler, less confusing)

**Estimated scope**: ~5 lines in `base_panel.py`

**Priority**: P2 — Misleading label but timestamps are consistent (all UTC).

---

### GAP-13: HTMX CDN Missing SRI Hash (BUG)

**Spec says**: HTMX loaded from CDN with SRI integrity hash for security.

**Built**: HTMX loaded from CDN without integrity attribute.

**Files affected**: `web_dashboard/shell.py` — HTMX script tag

**Implementation plan**:
1. Add `integrity="sha384-..."` and `crossorigin="anonymous"` to HTMX script tag
2. OR inline HTMX (14KB) per Mediator conflict resolution C-1 (eliminates CDN dependency entirely)

**Estimated scope**: ~2 lines in `shell.py`

**Priority**: P2 — Security hardening. Low risk for internal tool.

---

### GAP-14: Design System Simplified (SIMP)

**Spec says**: "Ops Intelligence" scheme with 20+ CSS custom properties, Inter font, 13px base, navy-tinted shadows.

**Built**: Functional design system with simpler token names, system font stack, reasonable defaults.

**Files affected**: `web_dashboard/shell.py` — CSS section

**Implementation plan**:
1. Align CSS custom property names to spec tokens
2. Add Inter font (system fallback, no CDN)
3. Adjust base font size to 13px
4. Add navy-tinted shadow variable
5. Fine-tune badge colors to match spec palette

**Estimated scope**: ~40 lines in `shell.py`

**Priority**: P3 — Cosmetic polish. Current design system is functional.

---

### GAP-15: Requests Table Not Auto-Refreshing (SIMP)

**Spec says**: Requests table auto-refreshes (implied by spec's pattern for other tables).

**Built**: Only Jobs/Monitor (10s) and System/Health (30s) auto-refresh. Requests table is static.

**Files affected**: `web_dashboard/panels/platform.py` — `_render_requests()`

**Implementation plan**:
1. Wrap requests table in auto-refresh div with `hx-trigger="every 15s [document.visibilityState === 'visible']"`
2. Add `_fragment_requests_table()` method for refresh response
3. Use `hx-include` to persist filter state across refreshes

**Estimated scope**: ~20 lines in `platform.py`

**Priority**: P2 — Operators monitoring active submissions would benefit from auto-refresh.

---

### GAP-16: Missing "View Logs" Link in Job Detail (BUD)

**Spec says**: Job detail card has "View Tasks", "View Lineage", and "View Logs" links.

**Built**: Only "View Tasks" and "View Pipeline" links.

**Files affected**: `web_dashboard/panels/jobs.py` — `_fragment_job_detail()`

**Implementation plan**:
1. Add "View Logs" link pointing to `/api/jobs/{job_id}/logs` (or an appropriate endpoint)
2. Determine if logs should open in a new panel section or as a modal/overlay

**Estimated scope**: ~5 lines in `jobs.py`

**Priority**: P3 — Convenience link. Operators can access logs through other paths.

---

## DEFERRED BY SPEC (Not Gaps)

These items were explicitly deferred by the Mediator (M) and should NOT be treated as Builder failures:

| ID | Item | Mediator Decision | Trigger to Revisit |
|----|------|-------------------|-------------------|
| D-1 | Authentication/Authorization | Platform-wide concern, not dashboard-specific | When auth is added to the API layer |
| D-2 | Dark mode toggle | CSS custom properties ready, toggle not built | User request or accessibility audit |
| D-3 | Keyboard shortcuts | Future enhancement | Power user feedback |
| D-4 | CSV export | Future enhancement | Reporting requirements |
| D-7 | Pending approval count badge | Avoid extra API call in MVP | When approval volume justifies it |
| D-8 | Real-time event timeline | WebSocket dependency | When event streaming is available |
| D-9 | Mobile responsive (<900px) | Minimum 900px for now | When field operators need mobile access |
| D-10 | Cursor-based pagination | Offset-based is sufficient | When datasets exceed 10K rows |

---

## Implementation Priority Summary

### P0 — Must Fix (Broken or Missing Core Functionality)

| Gap | Description | Scope | Files |
|-----|-------------|-------|-------|
| GAP-1 | Submit form stub → full wizard | ~400 lines | `platform.py`, `__init__.py` |
| GAP-2 | Request detail fragment not wired | ~15 lines | `platform.py` |
| GAP-4 | Health endpoint paths wrong | ~2 lines | `system.py` |

### P1 — Should Fix (Reduced Functionality or Security)

| Gap | Description | Scope | Files |
|-----|-------------|-------|-------|
| GAP-3 | Approval detail form missing | ~80 lines | `platform.py` |
| GAP-6 | Job monitor type filter + search | ~30 lines | `jobs.py` |
| GAP-9 | Filter selects missing HTMX triggers | ~15 lines | `base_panel.py` |
| GAP-10 | Action proxy URL injection | ~10 lines | `__init__.py` |
| GAP-11 | CSS class label XSS | ~5 lines | `base_panel.py` |

### P2 — Nice to Have (Polish and Convenience)

| Gap | Description | Scope | Files |
|-----|-------------|-------|-------|
| GAP-5 | Bottom status bar | ~60 lines | `shell.py` |
| GAP-7 | Job detail stage progress bars | ~40 lines | `jobs.py` |
| GAP-8 | Maintenance cleanup action | ~35 lines | `system.py`, `__init__.py` |
| GAP-12 | Timezone label incorrect | ~5 lines | `base_panel.py` |
| GAP-13 | HTMX CDN missing SRI hash | ~2 lines | `shell.py` |
| GAP-15 | Requests table auto-refresh | ~20 lines | `platform.py` |

### P3 — Low Priority (Cosmetic)

| Gap | Description | Scope | Files |
|-----|-------------|-------|-------|
| GAP-14 | Design system alignment | ~40 lines | `shell.py` |
| GAP-16 | Missing "View Logs" link | ~5 lines | `jobs.py` |

---

## Estimated Total Effort

| Priority | Gaps | Total Lines | Recommended Approach |
|----------|------|-------------|---------------------|
| P0 | 3 | ~420 | Single focused session — GAP-1 is the bulk |
| P1 | 5 | ~140 | Single session after P0, mostly small fixes |
| P2 | 6 | ~160 | Can be done incrementally across deploys |
| P3 | 2 | ~45 | Optional polish |
| **Total** | **16** | **~765** | |

GAP-1 (Submit form) accounts for more than half the total effort and should be tackled first as a standalone piece of work. The remaining P0 and P1 gaps are small targeted fixes that can be batched into a single session.

---

## Recommended Execution Order

1. **GAP-2 + GAP-4** (trivial bug fixes, ~17 lines) — unblock broken features immediately
2. **GAP-9 + GAP-10 + GAP-11** (bug fixes, ~30 lines) — security and UX fixes
3. **GAP-1** (submit form, ~400 lines) — major feature, needs its own session
4. **GAP-3 + GAP-6** (approval detail + job filters, ~110 lines) — functional improvements
5. **GAP-5 through GAP-16** (P2/P3) — polish as time allows

---

## Session 1 Results (02 MAR 2026)

### False Positives Identified

During implementation, code review revealed several Validator findings were either already fixed in v0.9.11.x patches or were false positives:

| Gap | Validator Finding | Actual State | Verdict |
|-----|-------------------|-------------|---------|
| GAP-2 | `request-detail` not wired in `render_fragment()` | Already in dispatch dict at line 78 | **False positive** — wiring exists |
| GAP-4 | Health paths missing `/api/` prefix | Paths already have `/api/` prefix at lines 104-105 | **False positive** — already correct |
| GAP-9 | Filter selects missing HTMX triggers | `filter_bar()` already has `hx-trigger="change from:find select"` at line 600 | **False positive** — already handled |
| GAP-10 | Action proxy URL injection | `urllib.parse.urlencode` already encodes params; API paths are hardcoded | **False positive** — not exploitable |

**Root cause**: The Validator (V) ran against the initial Builder output. Fixes applied in v0.9.11.0-v0.9.11.7 likely resolved GAP-2, GAP-4, and GAP-9 before this gap analysis was conducted. GAP-10 was a mischaracterization of how the action proxy constructs URLs.

### Changes Applied

| Gap | Change | Files | Lines |
|-----|--------|-------|-------|
| GAP-2 | Added "View Job" and "View Lineage" navigation links to request detail card | `platform.py` | +15 |
| GAP-11 | Added `re.sub()` CSS class sanitization in `stat_strip()` (defense in depth) | `base_panel.py` | +4 |
| GAP-3 | Reworked approvals: removed inline row buttons, added click-to-expand detail with clearance dropdown, reviewer input, and contextual action buttons | `platform.py` | +130/-50 |

### Remaining for Session 2

| Gap | Description | Priority |
|-----|-------------|----------|
| GAP-1 | Submit form — full wizard with file browser, DDH fields, type-specific options | P0 |

### Remaining for Session 3

| Gap | Description | Priority |
|-----|-------------|----------|
| GAP-6 | Job monitor type filter + search | P1 |
| GAP-5 | Bottom status bar | P2 |
| GAP-7 | Job detail stage progress bars | P2 |
| GAP-8 | Maintenance cleanup action | P2 |
| GAP-12 | Timezone label (UTC vs ET) | P2 |
| GAP-13 | HTMX CDN SRI hash | P2 |
| GAP-15 | Requests table auto-refresh | P2 |
| GAP-14 | Design system alignment | P3 |
| GAP-16 | Missing "View Logs" link | P3 |
