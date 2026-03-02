# Spec Diff: V's Blind Inferences vs S's Original Spec

**Pipeline**: GREENFIELD (narrow scope — submit form)
**Date**: 02 MAR 2026
**Method**: Compare V's blind code analysis against S's design spec + M's resolved spec

---

## PURPOSE ALIGNMENT

| Aspect | S's Spec | V's Inference | Match |
|--------|----------|---------------|-------|
| Core function | Replace _render_submit stub with HTMX file browser + submit form | "HTMX-driven data submission form... browse containers, select file, configure, submit" | EXACT |
| Validate/dry-run | Validate via dry run with inline result | Noted validate action in contracts | MATCH |
| CoreMachine job creation | Submit creates CoreMachine job | Noted submit → /api/platform/submit | MATCH |
| po_* restructuring | Flat form → nested processing_options | "restructuring po_*-prefixed form fields into nested processing_options dict" | EXACT |

**Verdict: V fully inferred the system's purpose from code alone.**

---

## CONTRACT ALIGNMENT

### _render_submit()
| Contract Element | S Specified | V Inferred | Match |
|-----------------|-------------|------------|-------|
| Hidden inputs (file_name, detected_data_type) | Yes | Yes | EXACT |
| Container select with hx-trigger="load" | Yes (via M) | Yes | EXACT |
| Prefix/suffix filters | Yes (Open Q #1) | Yes | EXACT |
| DDH identifier fields | Yes (6 fields) | Yes | EXACT |
| Metadata fields (title, access_level, description) | Yes | Yes | EXACT |
| Processing options placeholder | Yes | Yes | EXACT |
| Action buttons (Validate, Submit) | Yes | Yes | EXACT |
| Result display div | Yes | Yes | EXACT |

### _fragment_submit_containers()
| Contract Element | S Specified | V Inferred | Match |
|-----------------|-------------|------------|-------|
| API: GET /api/storage/containers?zone=bronze | Yes | Yes | EXACT |
| Returns <option> elements | Yes | Yes | EXACT |
| Error: disabled option on failure | Yes (via M) | Yes | EXACT |

### _fragment_submit_files()
| Contract Element | S Specified | V Inferred | Match |
|-----------------|-------------|------------|-------|
| Dual mode (listing + selection) | Yes (via M's C1 resolution) | Yes — Mode A / Mode B | EXACT |
| Mode A: clickable table rows | Yes | Yes | EXACT |
| Mode A: OOB-reset hidden inputs | Yes (via M) | Yes | EXACT |
| Mode B: selection display with badge | Yes (via M) | Yes | EXACT |
| Mode B: OOB-set hidden inputs | Yes (via M) | Yes | EXACT |
| Mode B: auto-load processing options | Yes (via M) | Yes | EXACT |
| URL double-escape (urllib + html) | Yes (via M's C6 resolution) | Yes — I-7 | EXACT |
| limit=500 | Yes | Yes — I-9 | EXACT |

### _fragment_submit_options()
| Contract Element | S Specified | V Inferred | Match |
|-----------------|-------------|------------|-------|
| Raster: po_crs, po_nodata_value, po_band_names | Yes | Yes | EXACT |
| Vector: po_table_name, po_layer_name, po_lat_column, po_lon_column, po_wkt_column | Yes | Yes | EXACT |
| Zarr: source_url (top-level, NOT po_ prefixed) | Yes — "source_url → PlatformRequest.source_url" | Yes — noted inconsistency | MATCH |
| Unknown/empty: placeholder message | Yes (via M) | Yes | EXACT |

### Action Proxy (_handle_action po_* restructuring)
| Contract Element | S Specified | V Inferred | Match |
|-----------------|-------------|------------|-------|
| Guard: action in ("submit", "validate") | Yes | Yes | EXACT |
| Collect po_* keys, strip prefix, nest under processing_options | Yes | Yes | EXACT |
| Strip detected_data_type, prefix_filter, suffix_filter | Yes (via M) | Yes — I-4 | EXACT |

---

## INVARIANT ALIGNMENT

| S's Invariant | V's Corresponding Invariant | Match |
|--------------|----------------------------|-------|
| 1. Field names match PlatformRequest DTO | I-3 (po_ prefix convention) + contract descriptions | MATCH |
| 2. Data type never user-selected | Inferred from EXTENSION_TO_TYPE auto-detection | MATCH |
| 3. File browser always queries bronze zone | I-8 | EXACT |
| 4. Selected file state in hidden input, not JS | I-2 (OOB swaps maintain hidden inputs) | EXACT |

**V discovered 6 additional invariants not in S's spec:**
- I-1: HTML escaping (S had this in NFRs, V elevated to invariant)
- I-5: Action dispatch whitelist (emergent from code structure)
- I-6: Always 200 responses (emergent from HTMX conventions)
- I-7: URL-encoding in hx-get (from M's double-escape resolution)
- I-9: 500 blob limit (S had in contracts, V elevated to invariant)
- I-10: Loopback HTTP pattern (pre-existing base_panel pattern)

**Verdict: V captured all 4 spec invariants and correctly identified 6 additional emergent invariants.**

---

## CONCERN MAPPING

### V's Concerns vs Spec Intent

| V Concern | Severity | Spec Intent | Assessment |
|-----------|----------|-------------|------------|
| C-1: zarr source_url not po_ prefixed | MEDIUM | INTENTIONAL — S says "source_url → PlatformRequest.source_url (required for zarr via abfs://)" — top-level API field, not a processing_option | FALSE POSITIVE — V correctly identified the naming inconsistency but the design is correct. A code comment explaining the exception would help. |
| C-2: parse_qs drops blanks | LOW | Not addressed in spec | VALID — minor, API handles missing fields |
| C-3: .json → vector overly broad | LOW | S includes .json in vector mapping | VALID — spec-aligned but V's concern is reasonable |
| C-4: No CSRF protection | MEDIUM | S: "No authentication enforced." M deferred CSRF. | KNOWN DEFERRAL — spec explicitly defers auth/CSRF |
| C-5: Error retry URL missing urllib.parse.quote | VERY LOW | M required double-escape for ALL dynamic URL values | VALID GAP — B missed double-escape in one error block |
| C-6: str truncation | VERY LOW | Not specified | NON-ISSUE |
| C-7: No required attributes on inputs | LOW | S NFR says "Required fields marked with required attribute" | VALID GAP — B missed this NFR requirement |
| C-8: Multi-valued form fields | VERY LOW | Not specified | NON-ISSUE |
| C-9: Host header spoofing | LOW | Pre-existing base_panel.py pattern | OUT OF SCOPE — inherited, not introduced |
| C-10: hx-confirm HTML entities | VERY LOW | Not specified | NON-ISSUE |

### Summary
- **False positives**: 1 (C-1 — zarr source_url is intentionally top-level)
- **Valid gaps found by V**: 2 (C-5 error URL escaping, C-7 required attributes)
- **Known deferrals**: 1 (C-4 CSRF)
- **Out of scope**: 1 (C-9 inherited pattern)
- **Non-issues**: 4 (C-2, C-6, C-8, C-10)
- **Spec-aligned but debatable**: 1 (C-3 .json mapping)

---

## SUCCESS CRITERIA VERIFICATION

| # | Criterion | Status | Notes |
|---|-----------|--------|-------|
| 1 | Container dropdown HTMX-populated | PASS | _fragment_submit_containers works via hx-trigger="load" |
| 2 | Browse and select file from blob list | PASS | Dual-mode _fragment_submit_files with OOB swaps |
| 3 | All DDH identifier fields with correct names | PASS | All 9 fields match PlatformRequest DTO names |
| 4 | Validate returns inline result | PARTIAL | Uses generic action proxy result card, not validation-specific formatting (blue card, lineage_state, suggested_params) |
| 5 | Submit shows result card with request_id, job_id, "View Request" link | PARTIAL | Uses generic action proxy result card, not submit-specific formatting (request_id, job_id, "View Request" link) |
| 6 | All dynamic content HTML-escaped | PASS | V confirmed comprehensive escaping (I-1) |
| 7 | No JavaScript — HTMX only | PASS | V confirmed zero JavaScript |
| 8 | Works on localhost and Azure | PASS | No platform-specific code |

---

## SPEC GAPS (B missed from S/M)

### GAP-V1: No `required` attribute on inputs (C-7 → S NFR)
S's NFR states: "Required fields marked with `required` attribute."
B omitted `required` on dataset_id and resource_id inputs.
**Fix**: Add `required` to dataset_id, resource_id, container_name inputs.

### GAP-V2: Error retry URL missing urllib.parse.quote (C-5 → M's C6 resolution)
M required double-escape for ALL dynamic values in hx-get attributes.
B applied this correctly in _fragment_submit_files select URLs but missed the error block retry URL.
**Fix**: Apply `urllib.parse.quote()` then `html_module.escape()` to container name in error retry URL.

### GAP-V3: Generic result cards instead of action-specific formatting (SC #4, #5)
S's spec included detailed API response schemas for submit success (request_id, job_id, job_type, monitor_url, warnings) and validate success (would_create_job_type, lineage_state, suggested_params, warnings). The action proxy returns generic key/value cards.
**Scope**: This was specified in S but the M resolved spec (Section 7) was explicit about result rendering. B used the pre-existing generic result card in __init__.py rather than adding submit-specific formatting.
**Impact**: Low — operators see all fields, just not in the optimized layout.
**Fix**: Deferred — would require modifying __init__.py _handle_action result rendering, which is shared infrastructure.

### GAP-V4: Add comment explaining zarr source_url naming exception (C-1)
V's C-1 flagged this. Not a bug — source_url is intentionally a top-level PlatformRequest field, not a processing_option. But the naming inconsistency deserves a code comment.
**Fix**: Add inline comment in _fragment_submit_options explaining why source_url is not po_ prefixed.

---

## PIPELINE EFFECTIVENESS METRICS

| Metric | Value |
|--------|-------|
| V correctly inferred purpose | Yes (100%) |
| V correctly inferred contracts | 8/8 (100%) |
| V correctly identified S's invariants | 4/4 (100%) |
| V discovered additional valid invariants | 6 |
| V concerns that are real gaps | 2 of 10 (20%) |
| V false positives | 1 of 10 (10%) |
| V non-issues | 4 of 10 (40%) |
| Success criteria fully met | 6/8 (75%) |
| Success criteria partially met | 2/8 (25%) |
| Real gaps found by V not in other agents | 0 (C-5 was in M's spec, C-7 was in S's NFRs) |

**Verdict**: V successfully validated the build quality as GOOD. The 2 real gaps (required attributes, error URL escaping) are minor and were already specified — B simply missed them. No new defects discovered that weren't already covered by the spec chain (S→M). The GREENFIELD pipeline's adversarial review successfully caught implementation gaps.
