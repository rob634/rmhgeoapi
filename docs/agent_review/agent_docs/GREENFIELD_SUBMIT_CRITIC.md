# Agent C — Critic Analysis: Dashboard Submit Panel

**Pipeline**: GREENFIELD (narrow scope — submit form)
**Date**: 02 MAR 2026
**Input**: Tier 1 spec only (no Design Constraints)

---

## AMBIGUITIES

### A-1: What constitutes "data type auto-detected from file extension"?

The spec says data type is "detected from file extension by the API" and "the form may display the detected type as informational only." But `_fragment_submit_options` takes a `data_type` param and renders type-specific fields.

**Interpretation 1**: The front-end detects the type from the file extension client-side (after file selection) and passes it to the options fragment.
**Interpretation 2**: The front-end calls a server-side API to detect the type, then passes the result to the options fragment.

**Why it matters**: Interpretation 1 requires client-side logic that must stay in sync with server-side mapping. Interpretation 2 requires an API call not specified in the spec.

### A-2: What does "action proxy" mean for validate vs. `_fragment_submit_validate`?

The CONTRACTS section defines `_fragment_submit_validate` and then says: "No separate fragment needed." But the method signature is still listed. Should the method exist or not?

### A-3: "No inline JavaScript" vs. HTMX click-to-select

Populating a hidden input from a table row click is not native HTMX without either inline JS, a custom extension, or a server round-trip.

**Interpretation 1**: Click triggers HTMX request returning fragment with hidden input pre-populated.
**Interpretation 2**: Small amount of inline JS allowed for this interaction.

### A-4: "Zarr submits via source_url — handle as text input fallback"

Listed as out of scope, yet "handle as text input fallback" implies some implementation. Is there a text input for source_url or not?

### A-5: What does `_fragment_submit_options` return for zarr?

Returns empty string per spec. But when would `data_type=zarr` ever be passed to this fragment?

---

## MISSING EDGE CASES

### E-1: Container API returns zero containers in the bronze zone
**Likelihood**: Low. **Severity**: Medium — empty dropdown with no explanation.

### E-2: Blob list returns exactly 500 items (the limit)
**Likelihood**: High. **Severity**: High — truncated list with no indication more files exist.

### E-3: File extension does not map to a known data type
**Likelihood**: Medium (`.nc4`, odd extensions). **Severity**: Medium.

### E-4: API call from `call_api` times out or returns non-JSON
Only `_fragment_submit_containers` specifies failure behavior. Other fragments don't.

### E-5: User submits the form without selecting a file
**Likelihood**: High. **Severity**: Low if API returns clear error, Medium if 500.

### E-6: User clicks validate, then immediately clicks submit
Concurrent actions through action proxy. Result div state unclear.

### E-7: Container or blob name contains HTML-special characters
**Severity**: High if unescaped — XSS or broken HTMX requests.

### E-8: User changes container selection after selecting a file
Hidden input still holds file_name from old container. **Severity**: High — wrong file submitted.

### E-9: Blob name contains URL-unsafe characters
Spaces, `#`, `?`, `%`, unicode in blob names used as URL parameters.

### E-10: previous_version_id — how does the user know what to enter?
Validate response includes `suggested_params.previous_version_id` but user must fill field before validating.

---

## UNSTATED ASSUMPTIONS

| ID | Assumption | Rating |
|----|-----------|--------|
| U-1 | "Do not modify" action proxy vs. adding po_* restructuring | RISKY — contradicts itself |
| U-2 | HTMX hx-include captures hidden inputs within included element | SAFE |
| U-3 | Storage API returns `zones` object with `bronze` key | RISKY — hardcoded zone name |
| U-4 | `call_api` works with path parameters like `/api/storage/{container}/blobs` | SAFE |
| U-5 | Blob API returns `size_mb` as float and `modified` as ISO 8601 | SAFE |
| U-6 | All data types use same DDH identifier fields | RISKY — zarr may differ |
| U-7 | Result div is replaced (not appended) on each action | SAFE |
| U-8 | Fragment dispatch is a simple dict lookup | SAFE |
| U-9 | Action proxy does not already handle po_* restructuring | RISKY — new logic in "do not modify" component |
| U-10 | PlatformRequest DTO field names are stable and known | RISKY — no complete field list provided |

---

## SPEC GAPS

| ID | Gap |
|----|-----|
| G-1 | No error handling contract for `_fragment_submit_files` or `_fragment_submit_options` |
| G-2 | No loading state specification (hx-indicator for slow blob list) |
| G-3 | No file selection UX flow detail (highlight, confirmation area, deselect) |
| G-4 | No form layout or field ordering specification |
| G-5 | No "View Request" link behavior specification (HTMX navigation mechanism) |
| G-6 | No handling of `warnings` array in submit/validate responses |
| G-7 | No `lineage_state` display specification for validate result |
| G-8 | No `suggested_params` handling specification |
| G-9 | No CSRF or request integrity protection |
| G-10 | No `access_level` field option values or default specified |
| G-11 | No "Back to file browser" button mechanism specification |
| G-12 | No suffix filtering UI element described |
| G-13 | No `monitor_url` handling in submit success |
| G-14 | No responsive/mobile behavior specified |

---

## CONTRADICTIONS

### C-1: "Do not modify `__init__.py`" vs. "Add `po_*` restructuring in `__init__.py`"
BOUNDARIES says changes to other modules are out of scope. CONTRACTS specifies explicit code to add to `__init__.py`.

### C-2: `_fragment_submit_validate` is both specified and declared unnecessary
Listed as method to implement with full signature, then says "No separate fragment needed." Not in fragment dispatch additions either.

### C-3: Invariant 2 vs. `_fragment_submit_options` contract
Invariant 2: "Data type is never user-selected." But something must determine data_type before calling the options fragment. Front-end extension detection is a form of client-side detection that Invariant 2 seems to prohibit.

### C-4: Boundaries say "No changes to `base_panel.py`" but security NFR demands specific escape patterns
If BasePanel utilities don't already escape inputs, developer must change base_panel.py or double-escape.

---

## OPEN QUESTIONS (Ranked by Impact)

### Q-1 (CRITICAL): How does the form determine data type without violating Invariant 2?
Core interaction loop blocks entirely on this answer.

### Q-2 (CRITICAL): Is the `__init__.py` modification in scope or out of scope?
Without po_* restructuring, processing options sent as flat keys — API will reject.

### Q-3 (HIGH): How does "click-to-select" work without inline JavaScript?
Server round-trip vs. JS exception needed. Affects core file selection UX.

### Q-4 (HIGH): What happens when blob list exceeds 500 items?
Pagination, truncation message, or nothing?

### Q-5 (HIGH): What are the exact DTO field names for PlatformRequest?
Invariant 1 says match exactly but spec doesn't provide complete list.

### Q-6 (MEDIUM): Should selected file be cleared when container changes?
See E-8 — wrong-file submission risk.

### Q-7 (MEDIUM): How should `suggested_params` from validate be applied?
Auto-populating form fields from validate response is non-trivial in HTMX.

### Q-8 (MEDIUM): Should file browser support prefix filtering?
Recommended yes but no UI element described.

### Q-9 (LOW): Should processing_options be collapsible?
Cosmetic only.

### Q-10 (MEDIUM): What is the complete list of type-specific processing option fields?
Spec mentions `po_table_name` as example but never enumerates all fields.
