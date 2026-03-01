# COMPETE Run 18: Web Interface Core Workflow

**Date**: 01 MAR 2026
**Pipeline**: COMPETE (Adversarial Review)
**Scope**: `web_interfaces/` — pipeline → submit → status → platform
**Complexity**: Medium (6 files, ~13,700 lines)
**Split**: B (Internal vs External)

---

## Token Usage

| Agent | Role | Input+Output | Tool Uses | Duration |
|-------|------|-------------|-----------|----------|
| Omega | Scope split (Claude direct) | — | — | — |
| Alpha | Internal logic & invariants | 100,244 | 44 | 288s |
| Beta | External interfaces & security | 78,856 | 38 | 302s |
| Gamma | Contradictions & blind spots | 161,814 | 28 | 215s |
| Delta | Final report | 46,808 | 28 | 148s |
| **Total** | | **387,722** | **138** | **953s** |

---

## EXECUTIVE SUMMARY

The web interface subsystem has a systemic output-encoding deficiency. Zero of the five interface files use `html.escape()` on user-controlled or data-driven content; the only escaping in the entire subsystem is three calls in the error handler of `__init__.py`, which itself is broken by a variable shadowing bug (CTR-2). The most exploitable finding is BLIND-1: a trivially weaponizable reflected XSS via the `job_id` URL parameter in the tasks/status interface that requires no authentication and no special preconditions — just a crafted link. The submit interface has four distinct injection surfaces from Azure blob/container names and URL parameters. While this is an internal dev tool with no public auth gateway, the XSS surface means any link shared in Slack, email, or a browser bookmark could execute arbitrary JavaScript in the operator's browser session. The architecture itself (registry pattern, base class, HTMX fragments) is sound and provides a clean path toward centralized remediation.

---

## TOP 5 FIXES

### Fix 1: Escape URL parameters in tasks/interface.py `_generate_custom_js`

- **WHAT**: Add escaping for all URL-sourced parameters interpolated into JavaScript string literals.
- **WHY**: BLIND-1 — Reflected XSS. An attacker crafts a URL like `/api/interface/status?job_id=';alert(document.cookie);//` and the payload executes immediately. No authentication required, no stored data needed. This is the single most dangerous finding because it is trivially exploitable via a shared link.
- **WHERE**: `web_interfaces/tasks/interface.py`, method `_generate_custom_js`, lines 3073-3078. The parameters `lookup_id`, `dataset_id`, `resource_id`, `release_id` are interpolated from `request.params.get()` (lines 55-60) directly into JS string literals via f-string.
- **HOW**: Add a `_js_escape()` static method on `BaseInterface`:
  ```python
  @staticmethod
  def _js_escape(value: str) -> str:
      """Escape a string for safe embedding in a JS single-quoted literal."""
      return (value
          .replace('\\', '\\\\')
          .replace("'", "\\'")
          .replace('"', '\\"')
          .replace('<', '\\x3c')
          .replace('>', '\\x3e')
          .replace('\n', '\\n')
          .replace('\r', '\\r'))
  ```
  Then: `const LOOKUP_ID = '{self._js_escape(lookup_id)}';` for all four constants. Also apply `html.escape()` where `lookup_id` is interpolated into HTML `<title>` and `<span>` (lines 74, 77).
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low. Pure output encoding, no logic change.

### Fix 2: Escape blob/container names and zone parameter in submit/interface.py

- **WHAT**: Apply `html.escape()` to all blob names, container names, and the zone parameter before HTML interpolation.
- **WHY**: CRITICAL-1 through CRITICAL-3 and BLIND-4. Azure blob names can contain `"`, `<`, `>` which break out of HTML attributes and JS strings. The `zone` parameter is reflected from the URL query string.
- **WHERE**: `web_interfaces/submit/interface.py`:
  - Line 110: `f'<option value="">Invalid zone: {zone}</option>'`
  - Line 121: `f'<option value="{c["name"]}">{c["name"]}</option>'`
  - Lines 203, 206, 211: `data-blob="{name}"`, `title="{name}"`
  - Line 227: `onclick="selectFile('{name}', '{container}', '{zone}', ...)"` (double context: JS + HTML)
- **HOW**: `import html as html_mod` at top. For HTML: `html_mod.escape(name, quote=True)`. For line 227 (JS in HTML attr): apply `_js_escape()` first, then `html_mod.escape()`.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low.

### Fix 3: Fix `html` variable shadowing in `__init__.py`

- **WHAT**: Rename local variable `html` to `html_content` to stop shadowing the `html` stdlib module.
- **WHY**: CTR-2. If `interface.render()` raises, the error handler calls `html.escape()` which raises `UnboundLocalError` — the error handler itself crashes, masking the original error with an opaque 500.
- **WHERE**: `web_interfaces/__init__.py`, function `unified_interface_handler`, lines 206, 209, 217, 229.
- **HOW**: Replace `html = interface.htmx_partial(...)` → `html_content = ...` and `html = interface.render(...)` → `html_content = ...`. Update return statements.
- **EFFORT**: Small (< 30 minutes).
- **RISK OF FIX**: Low. Variable rename within a single function.

### Fix 4: Sanitize innerHTML assignments across pipeline and tasks JS

- **WHAT**: Wrap all API response data in `escapeHtml()` before innerHTML insertion; validate URL protocols.
- **WHY**: HIGH-1, HIGH-2, HIGH-3. Pipeline jobs table and tasks platform status insert API fields (`job_type`, `status`, `dataset_id`, `blob_path`, error messages, service URLs) directly into innerHTML. Service links allow `javascript:` URLs.
- **WHERE**:
  - `web_interfaces/pipeline/interface.py`, `renderJobsTable`, lines 710-738.
  - `web_interfaces/tasks/interface.py`, `renderPlatformSummary`, lines 3331, 3416-3498. Service links at line 3435. `formatJsonWithHighlighting` lines 3170-3178 (BLIND-6).
- **HOW**: `escapeHtml()` already exists in base COMMON_JS. Wrap all interpolated API values: `${escapeHtml(job.job_type)}`. For service URLs: `if (!/^https?:\/\//i.test(url)) return;`. For `formatJsonWithHighlighting`: apply `escapeHtml()` to the JSON string before regex replacement.
- **EFFORT**: Medium (2-3 hours). Many template literals across two files.
- **RISK OF FIX**: Low. Test all UI views after.

### Fix 5: Escape error messages and validation warnings in submit/interface.py

- **WHAT**: Apply `html.escape()` to all exception messages and validation warning strings.
- **WHY**: HIGH-4, HIGH-5, HIGH-6. Exception messages (may contain file paths, SQL errors) and API validation warnings rendered directly as HTML.
- **WHERE**: `web_interfaces/submit/interface.py`:
  - `_render_files_error`, line 273: `<p>{message}</p>`
  - `_render_validate_fragment`, lines 569, 590: `{w}` in warning divs
  - `_render_submit_success`, lines 818-834: result dict values
  - `_render_submit_error`, line 854: `{message}`
- **HOW**: `html_mod.escape(str(message))` for all dynamic values.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low.

---

## ACCEPTED RISKS

### A1: CSP `frame-ancestors *` allows clickjacking
`__init__.py` line 225. Intentional for DDH iframe embedding. No auth means clickjacking has limited impact.
**Revisit if**: Authentication is added.

### A2: No CSRF protection on HTMX POST endpoints
No auth layer means no session-bound privileges to abuse. Same endpoints reachable via `curl`.
**Revisit if**: Authentication is added.

### A3: Hardcoded WORKFLOW_DEFINITIONS (tasks lines 3087-3161)
Maintainability concern, not security. Adding a job type requires updating this dict. Generic fallback works.
**Revisit if**: Job types change frequently enough to cause operator confusion.

### A4: Validation bypass via direct HTMX fragment call (C1/C8)
Submit fragment skips collection file count validation. Platform API does server-side validation, so this is UX convenience not security gate.
**Revisit if**: Client-only validation rules are added not enforced by API.

### A5: `formatJsonWithHighlighting` regex fragility (BLIND-6)
Job parameters are system-generated, not direct user input. Included in Fix 4 scope but deferrable.
**Revisit if**: Job parameters include user-supplied free-text.

---

## ARCHITECTURE WINS

### W1: Registry pattern with decorator-based registration
`InterfaceRegistry` in `__init__.py` (lines 23-80). Clean, extensible. Adding an interface = one decorator. Single HTTP entry point. Preserve this.

### W2: BaseInterface with shared utilities
`base.py` centralizes HTML skeleton, navigation, badges, orchestrator URL. Correct place to add `_js_escape()` and ensure `escapeHtml()` is universally available.

### W3: HTMX fragment architecture
`htmx_partial()` method pattern — each interface declares fragments, router dispatches on `fragment` param. Stateless, composable. Submit's 3-phase flow (containers → validate → submit) maps naturally.

### W4: Platform interface as reference pattern
Server-side generates only static HTML structure; all dynamic data rendered client-side via HTMX fetch. This minimizes server-side XSS surface. Future interfaces should follow this pattern.

---

## ALL FINDINGS (Unified Severity)

### CRITICAL (6)
| ID | Finding | File | Lines |
|----|---------|------|-------|
| BLIND-1 | Reflected XSS via URL params in JS string literals | tasks/interface.py | 55-60, 3074-3078 |
| CRIT-1 | Stored XSS via blob names in HTML f-strings | submit/interface.py | 200-242 |
| CRIT-2 | Stored XSS via container names in `<option>` | submit/interface.py | 121 |
| CRIT-3 | Reflected XSS via zone parameter | submit/interface.py | 110 |
| BLIND-4 | Stored XSS via blob names in onclick handler | submit/interface.py | 227 |
| BLIND-6 | Stored XSS via job params in formatJsonWithHighlighting | tasks/interface.py | 3170-3178, 3786 |

### HIGH (8)
| ID | Finding | File | Lines |
|----|---------|------|-------|
| HIGH-1 | Client XSS in pipeline jobs table innerHTML | pipeline/interface.py | 710-738 |
| HIGH-2 | Client XSS in tasks platform status innerHTML | tasks/interface.py | 3331, 3416-3498 |
| HIGH-3 | javascript: URL in service links | tasks/interface.py | 3435 |
| HIGH-4 | Server XSS in submit error handlers | submit/interface.py | 265-277, 848-859 |
| HIGH-5 | Server XSS in submit validation warnings | submit/interface.py | 568-590 |
| HIGH-6 | Server XSS in submit success result | submit/interface.py | 794-846 |
| C1/C8 | Payload duplication + validation bypass | submit/interface.py | 280-437 vs 604-738 |
| CTR-2 | html module shadowing crashes error handler | __init__.py | 14, 206, 217, 246 |

### MEDIUM (18)
| ID | Finding | File | Lines |
|----|---------|------|-------|
| M-1 | Unescaped `<title>` tag | base.py | 2079 |
| M-2 | render_status_badge skips escaping | base.py | 2266-2275 |
| M-3 | render_asset_header unescaped dict values | base.py | 2292-2308 |
| M-4 | Unvalidated `limit` param ValueError | submit/interface.py | 134 |
| M-5 | No auth on self-call to Platform API | submit/interface.py | 440-460 |
| M-6 | XSS via job_id in onclick handler | tasks/interface.py | 3763-3764 |
| M-7 | CSP frame-ancestors * clickjacking | __init__.py | 212, 224-226 |
| M-8 | Unescaped queryInfo.schema | pipeline/interface.py | 702 |
| M-9 | Orchestrator URL in JS without escaping | base.py | 2120 |
| M-10 | Approval panel error unescaped | tasks/interface.py | 5424 |
| M-11 | Version table fields unescaped | tasks/interface.py | 3453-3467 |
| C4 | Flawed stage status priority | tasks/interface.py | 4087-4092 |
| C5 | WORKFLOW_DEFINITIONS incomplete | tasks/interface.py | 3087-3161 |
| C6 | Pipeline type names hardcoded 3x | pipeline/interface.py | 682-687 |
| C7 | CSS duplication pipeline vs base | pipeline/interface.py | 54-61, 313-339 |
| C11 | Revoke hardcodes reviewer | tasks/interface.py | 5719-5722 |
| C3 | Platform badge reimplementation | platform/interface.py | 336-375 |
| BLIND-5 | Self-call DOS amplification | submit/interface.py | 440-460, 741-760 |

### LOW (11)
| ID | Finding | File | Lines |
|----|---------|------|-------|
| R-2 | Promise.all failure in tasks | tasks/interface.py | 3354-3357 |
| R-3 | No CSRF on HTMX POST | submit/interface.py | — |
| R-4 | HTMX CDN dependency | base.py | 2067 |
| C10 | fetchJSON vs raw fetch inconsistency | tasks/interface.py | 5200, 5366 |
| C12 | formatJsonWithHighlighting regex fragile | tasks/interface.py | 3170-3178 |
| C13 | isDockerJob naming fallback | tasks/interface.py | 3164-3167 |
| C14 | Navbar missing Platform link | base.py | 2146-2203 |
| C15 | urllib import inside method body | submit/interface.py | 440-442, 741-743 |
| C16 | Inline JS redirect instead of HX-Redirect | platform/interface.py | 103 |
| E-3 | Timezone import inside loop | submit/interface.py | 181 |
| E-5 | DATASET_ID unencoded in API URL | tasks/interface.py | 3310-3311 |

### INVALIDATED (1)
| ID | Finding | Reason |
|----|---------|--------|
| C2 | "Dead execution link" | execution interface IS registered — Alpha checked only the 6 scoped files |

---

## KEY CORRECTIONS FROM GAMMA

1. **Alpha C2 invalidated**: The `/api/interface/execution` link is NOT dead — `execution/interface.py` registers it. Alpha only searched the 6 in-scope files.
2. **CTR-2 upgraded**: `html` variable shadowing is not just "fragile" (Alpha C9 MEDIUM) — it causes `UnboundLocalError` in the error handler, masking original errors.
3. **BLIND-1 discovered**: Neither reviewer caught the most dangerous finding — JS string injection via URL parameters into `<script>` blocks.
