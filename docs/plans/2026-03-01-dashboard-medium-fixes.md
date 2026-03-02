# Fix 5 MEDIUM Validator Findings — Implementation Plan

**Date**: 01 MAR 2026
**Source**: GREENFIELD Validator Report (Agent V)

---

## Findings Overview

| ID | Title | Files | Effort |
|----|-------|-------|--------|
| M-1 | Deduplicate API call infrastructure | `__init__.py`, `base_panel.py` | Medium |
| M-2 | Add SRI hash to HTMX CDN fallback | `shell.py` | Low |
| M-3 | Cache panel instances in registry | `registry.py`, `__init__.py` | Medium |
| M-4 | Fix double-escaping of row_attrs | `panels/platform.py` | Low |
| M-5 | Fix timezone label (UTC not ET) | `base_panel.py` | Low |

---

## Step 1: M-5 — Fix timezone label

**File**: `web_dashboard/base_panel.py` line 196

**Change**: Replace `"ET"` with `"UTC"`. The DB stores UTC timestamps and there's no conversion happening — labeling them "ET" is just wrong.

```python
# Before
dt.strftime("%d %b %Y %H:%M ET").upper()

# After
dt.strftime("%d %b %Y %H:%M UTC").upper()
```

One line. No behavioral change other than correct labeling.

---

## Step 2: M-2 — Add SRI hash to HTMX CDN fallback

**File**: `web_dashboard/shell.py` lines 60-62

**Change**: Add `s.integrity` attribute with the sha384 hash for htmx 1.9.12. Need to fetch the correct hash from the CDN or compute it.

```python
# Before
s.src = 'https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js';
s.crossOrigin = 'anonymous';

# After
s.src = 'https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js';
s.integrity = 'sha384-<correct-hash>';
s.crossOrigin = 'anonymous';
```

One line addition. Need to look up the correct SRI hash for htmx 1.9.12.

---

## Step 3: M-4 — Fix double-escaping of row_attrs

**File**: `web_dashboard/panels/platform.py` lines 167, 350

**What's happening**: `data_table()` in `base_panel.py:357` escapes all `row_attrs` values. But callers in `platform.py` pre-escape the `id` and `hx-get` values before passing them. This causes double-escaping.

**Fix**: Remove the pre-escaping from callers. Let `data_table()` handle it (it already does).

```python
# Before (platform.py:167)
"id": f"row-{html_module.escape(str(req_id)[:8])}",

# After
"id": f"row-{str(req_id)[:8]}",
```

Same for line 350 and the `hx-get` value on line 169. Check `jobs.py` for the same pattern.

---

## Step 4: M-3 — Cache panel instances in registry

**File**: `web_dashboard/registry.py`, `web_dashboard/__init__.py`

**Problem**: `get_ordered()` instantiates ALL panels on every call. `_get_panel()` instantiates again. A full page load creates 5+ panel objects.

**Fix**: Cache instances in the registry as a lazy singleton dict. Panels are stateless so reuse is safe.

Changes to `registry.py`:
- Add `_instances: Dict[str, Any] = {}` class variable
- Add `get_instance(name)` classmethod that returns cached instance
- Modify `get_ordered()` to use cached instances

Changes to `__init__.py`:
- Replace `_get_panel()` to use `PanelRegistry.get_instance(tab)` instead of `panel_class()`

---

## Step 5: M-1 — Deduplicate API call infrastructure

**Files**: `web_dashboard/__init__.py` (lines 402-466), `web_dashboard/base_panel.py` (lines 242-326)

**Problem**: `_call_api_direct()` in `__init__.py` duplicates `BasePanel.call_api()` and `BasePanel._get_base_url()` — ~60 lines of identical scheme detection, urllib.request pattern, and error handling. They also have inconsistent timeouts (15s vs 10s).

**Fix**: Extract `_get_base_url()` and `call_api()` from `BasePanel` into a module-level helper function, then:
1. Move `_get_base_url` to a standalone function in `base_panel.py` (or a small `_http.py` utility)
2. Move `call_api` to a standalone function that takes `request` as first arg
3. Have `BasePanel.call_api()` delegate to the standalone function
4. Replace `_call_api_direct()` in `__init__.py` with a call to the same standalone function
5. Unify timeout to 10s (with override param where needed)

Simplest approach: make `_get_base_url` and `call_api` static methods on `BasePanel`, then import `BasePanel` in `__init__.py` and use `BasePanel.call_api_static(request, path, ...)`. This avoids creating a new file.

---

## Execution Order

1. **M-5** (1 line) — lowest risk, immediate correctness win
2. **M-2** (1 line + hash lookup) — security improvement
3. **M-4** (2-4 lines) — correctness fix, remove redundant code
4. **M-3** (~20 lines) — refactor, improves performance
5. **M-1** (~30 lines) — largest refactor, consolidates duplication

## Validation

After all changes: `py_compile` all 9 dashboard files to verify no syntax errors.
