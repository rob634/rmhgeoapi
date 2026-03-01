# GREENFIELD: Platform Dashboard — Spec Diff (S vs V)

**Date**: 01 MAR 2026
**Pipeline**: GREENFIELD Run 19 (7-agent: S → A+C+O → M → B → V)
**Method**: Compare Agent V's inferred purpose/contracts/invariants against Agent S's original spec

---

## MATCHES

Code successfully implements what the spec intended:

| Spec Requirement | V's Inference | Match |
|------------------|---------------|-------|
| SSR Python + HTMX, no JS framework | "No JavaScript business logic of its own" | EXACT |
| Top tabs + sub-tabs layout | 4 tabs, 18 sub-tabs across all panels | EXACT |
| Operator power-user dashboard | "Internal operators... not a public-facing consumer UI" | EXACT |
| HTMX fragment switching for tabs | Full dispatch hierarchy: full page / tab / section / fragment / action | EXACT |
| PanelRegistry decorator pattern | Self-describing @register, auto-discovery via pkgutil | EXACT |
| BasePanel abstract + utilities | 6 abstract methods, 16 utility methods | EXACT |
| Dashboard proxy for JSON→HTML | Action allowlist, form-encoded→JSON translation | EXACT |
| Auto-refresh with visibility guard | Jobs 10s, Health 30s, both guarded | EXACT |
| Error isolation per panel | Try/except in handler + all render paths | EXACT |
| HTML escaping on user data | "Applied correctly in the vast majority of places" | NEAR (see gaps) |
| Military date format | `DD MMM YYYY HH:MM` uppercase | MATCH (but timezone wrong) |
| Status badge color scheme | All badge types implemented per spec tokens | EXACT |
| hx-push-url for browser history | Tab and sub-tab switches push URL | EXACT |
| Old /api/interface/* preserved | Dashboard is additive, new /api/dashboard route only | EXACT |
| Safe import in function_app.py | try/except with 503 fallback, _dashboard_available flag | EXACT |
| Default tabs: platform/requests | Confirmed via end-to-end trace | EXACT |

---

## GAPS

Where the code does NOT match the spec:

### Implementation Gaps (bugs in code)

| # | Spec Says | Code Does | Severity | V Finding |
|---|-----------|-----------|----------|-----------|
| 1 | System Health calls `/api/health` and `/api/system-health` | Calls `/health` and `/system-health` (missing /api/ prefix) | CRITICAL | C-1 |
| 2 | Request rows are clickable with detail drill-down | `render_fragment()` has no `request-detail` handler; clicks produce silent errors | CRITICAL | C-2 |
| 3 | Filters update the table when changed | `<select>` has no HTMX trigger; Refresh button resets filters | HIGH | H-3 + L-3 |
| 4 | Action proxy URL-encodes parameters | Raw string concatenation, no `urlencode()` | HIGH | H-1 |
| 5 | `stat_strip()` CSS class is safe | API-controlled label injected into class attribute without escaping | HIGH | H-2 |
| 6 | Timestamps show Eastern Time | UTC timestamps labeled "ET" without timezone conversion | MEDIUM | M-5 |
| 7 | CDN fallback has SRI integrity | No integrity hash on fallback script tag | MEDIUM | M-2 |

### Documentation Gaps (code is correct but unclear)

| # | Issue | Impact |
|---|-------|--------|
| 1 | `_call_api_direct()` duplicates `call_api()` with different timeout | Maintenance burden, inconsistent behavior |
| 2 | Storage and Queues sub-tabs are visible but placeholder-only | User confusion ("tabs that go nowhere") |
| 3 | Double-escaping of row IDs in data_table callers | No visible defect (UUIDs have no special chars) but semantically wrong |

---

## EXTRAS (scope creep or undocumented behavior)

| # | What V Found | Spec Position |
|---|-------------|---------------|
| 1 | `loading_placeholder()` utility method | Not in Mediator spec, but useful. KEEP. |
| 2 | `pagination_controls()` with offset-based UI | Spec said offset-based, implementation is reasonable. KEEP. |
| 3 | `data_type_badge()` utility | Not explicitly in spec but consistent with pattern. KEEP. |

No significant scope creep detected. The Builder stayed within spec boundaries.

---

## VERDICT

### Overall: PASS WITH REQUIRED FIXES

The Builder produced a **B- grade** codebase (per Validator) that correctly implements the spec architecture, dispatch model, HTMX protocol, design system, and error handling. The code is well-organized and a developer can understand it quickly.

**However, 2 CRITICAL and 3 HIGH findings must be fixed before deployment:**

| Priority | Fix | Effort |
|----------|-----|--------|
| P0 | Fix health endpoint paths (`/api/health`, `/api/system-health`) | 1 line each |
| P0 | Add `request-detail` fragment handler + `.detail-panel` div to Platform panel | ~30 lines |
| P1 | Fix filter bar: add HTMX triggers to `<select>`, include filter params in Refresh URL | ~15 lines |
| P1 | Fix action proxy URL construction: use `urllib.parse.urlencode()` | 1 line |
| P1 | Escape `stat_strip()` CSS class label | 1 line |

**Post-fix effort**: ~50 lines of changes. No architectural rework needed.

### MEDIUM items (fix before deploy, not blocking):
- Fix timezone label (UTC not ET) or convert properly
- Add SRI hash to CDN fallback script
- Deduplicate `_call_api_direct` / `call_api`

---

## PIPELINE METRICS

| Agent | Role | Output | Tokens (est.) | Duration |
|-------|------|--------|---------------|----------|
| S | Spec Writer | Master spec doc (440 lines) | — | Pre-existing |
| A | Advocate | Design doc (84KB, ~1800 lines) | ~83K | ~7.4 min |
| C | Critic | 52 findings (inline report) | ~74K | ~6.2 min |
| O | Operator | Assessment doc (609 lines) | ~64K | ~4.6 min |
| M | Mediator | Resolved spec (~1100 lines) | ~99K | ~7.0 min |
| B | Builder | 9 code files (4,117 lines) + 1 edit | ~114K | ~11.3 min |
| V | Validator | Validation report (353 lines) | ~116K | ~8.4 min |
| **Total** | | **~8,400 lines of output** | **~550K** | **~45 min** |

---

## DOCUMENTS PRODUCED

| File | Agent | Purpose |
|------|-------|---------|
| `GREENFIELD_PLATFORM_DASHBOARD.md` | S (pre-existing) | Original spec + Tier 1 context |
| `GREENFIELD_ADVOCATE_DESIGN.md` | A | Optimal design proposal |
| (Critic report inline) | C | 52 findings |
| `GREENFIELD_PLATFORM_DASHBOARD_AGENT_O.md` | O | Operational assessment |
| `GREENFIELD_MEDIATOR_DASHBOARD.md` | M | Resolved spec for Builder |
| `GREENFIELD_VALIDATOR_DASHBOARD.md` | V | Code quality validation |
| `GREENFIELD_DASHBOARD_SPEC_DIFF.md` | Claude | This document — final comparison |

## CODE PRODUCED

| File | Lines | Status |
|------|-------|--------|
| `web_dashboard/__init__.py` | 471 | Needs H-1 fix (urlencode) |
| `web_dashboard/registry.py` | 129 | Clean |
| `web_dashboard/base_panel.py` | 614 | Needs H-2, H-3, M-5 fixes |
| `web_dashboard/shell.py` | 1001 | Needs M-2 fix (SRI hash) |
| `web_dashboard/panels/__init__.py` | 34 | Clean |
| `web_dashboard/panels/platform.py` | 643 | Needs C-2 fix (request-detail) |
| `web_dashboard/panels/jobs.py` | 534 | Clean |
| `web_dashboard/panels/data.py` | 344 | Clean |
| `web_dashboard/panels/system.py` | 347 | Needs C-1 fix (health paths) |
| `function_app.py` (edit) | +15 | Clean |

---

*GREENFIELD Run 19 complete. Next step: Fix P0/P1 findings, then deploy and test.*
