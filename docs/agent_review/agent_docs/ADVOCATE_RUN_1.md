# ADVOCATE Report — Run 1

**Date**: 03 MAR 2026
**Version**: 0.9.12.0
**Target**: `https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net`
**Pipeline**: ADVOCATE (B2B Developer Experience Audit)
**Agents**: Intern (first impressions) → Architect (structured audit)
**Run Number**: 31 (global)

---

## Executive Summary

The DDH Geospatial Platform API has a solid processing backbone — SHA256 idempotent submissions, STAC/OGC standards compliance, and a well-designed Job→Stage→Task orchestration engine. However, the developer-facing API surface has accumulated five systemic problems that would block B2B adoption:

1. **Dead URLs in every response** — `job_status_url` returns 404 on every submit, creating a first-contact failure for every integration partner.
2. **State machine integrity violation** — approval succeeds on failed/unprocessed releases, setting `is_served=true` on data that doesn't exist.
3. **Five incompatible error shapes** — a client cannot build a unified error handler without endpoint-specific parsing.
4. **Write-only API** — `services` and `outputs` fields are permanently null, leaving developers with no programmatic path from "approved" to "consume."
5. **Silent parameter ignoring** — pagination and filter params on key list endpoints have no effect but return 200.

Benchmarked against Stripe, Twilio, and Azure's own APIs, this is at a **pre-beta integration quality level**. The data model and processing architecture are sophisticated, but the API surface needs systematic polish before external developers can integrate.

---

## DX Score: 37%

| Category | Weight | Score | Notes |
|----------|--------|-------|-------|
| Discoverability | 20% | 40% | OpenAPI spec exists but is hidden. No `/api/` landing, no Swagger UI, TiTiler not cross-linked. |
| Error Quality | 20% | 25% | 5 distinct error shapes. Malformed JSON on `/approve` returns 500. `error: null` on failed jobs. `error_summary: "Unknown error"` for all failures. |
| Consistency | 20% | 30% | `/approvals` dumps 44-field raw rows vs `/status` curated 18-field versions. Naming mixes singular/plural. Error envelopes vary per endpoint. |
| Response Design | 15% | 45% | Status list/detail split is well-designed. But 45% null density in approvals. `services`/`outputs` never populated. |
| Service URL Integrity | 15% | 40% | `job_status_url` permanently broken. `services` always null. But TiTiler works independently, STAC/OGC standards met. |
| Workflow Clarity | 10% | 50% | Submit→poll→approve lifecycle works. Idempotency is A-tier. But approval accepts failed releases. Silent param ignoring misleads developers. |

**Weighted Score**: (0.20×40) + (0.20×25) + (0.20×30) + (0.15×45) + (0.15×40) + (0.10×50) = **36.75% ≈ 37%**

---

## Themes

### Theme 1: Broken Contract — Dead URLs in Responses
**Severity**: CRITICAL
**Affected endpoints**: `POST /api/platform/submit` (all responses)
**Intern's experience**: Followed `job_status_url` as first action after submit — immediate 404. Spent significant time trying URL variations before discovering `monitor_url` works.
**Architect's analysis**: `_generate_job_status_url()` in `platform_response.py:47` generates `/api/platform/jobs/{job_id}/status` — no route exists. The working endpoint is `monitor_url` at `/api/platform/status/{request_id}`. Additionally, `monitor_url` is relative while `job_status_url` is absolute — inconsistent within the same response.
**Recommendation**: Delete `job_status_url` entirely. Make `monitor_url` absolute. Single URL field that always works (Stripe pattern).
**Effort**: S

### Theme 2: State Machine Integrity Violation
**Severity**: CRITICAL
**Affected endpoints**: `POST /api/platform/approve`
**Intern's experience**: Approved vector and NetCDF data whose jobs had failed. System returned `is_served: true` on data that was never processed. No guardrails.
**Architect's analysis**: No pre-condition check on `processing_status` or `job_status` before approval. Confirmed across 3 test datasets — `job_status=failed`, `processing_status=pending`, `approval_state=approved`, `is_served=true`. Known issue SG5-1/LA-1 — reconfirmed across 4 separate pipeline runs (SIEGE 25, SIEGE 26, TOURNAMENT 27, ADVOCATE 31).
**Recommendation**: Add guard: `if release.processing_status != 'completed': return 409 Conflict`. This is a data integrity violation — the system claims to serve data that was never processed.
**Effort**: M

### Theme 3: Five Error Shapes
**Severity**: HIGH
**Affected endpoints**: All platform endpoints
**Intern's experience**: Every error looked different. Couldn't build a reusable error parser. Had to inspect each response individually.
**Architect's analysis**: Identified 5 distinct schemas:

| Shape | Endpoints | Fields |
|-------|-----------|--------|
| A | `/submit`, `/approve`, `/reject`, `/revoke`, `/unpublish` | `{success, error, error_type}` |
| B | `/status/{id}` 404 | `{success, error, hint}` — missing `error_type` |
| C | `/lineage/{id}` 404 | `{success, error, error_type, timestamp}` — extra field |
| D | `/catalog/assets` 404 | `{error, message, collection_id, item_id}` — no `success` |
| E | STAC/OGC 404 | `{code, description}` — external standard |

Additionally: `/submit` uses Pydantic multi-line errors, `/approve` uses flat strings, malformed JSON on `/approve`/`/reject`/`/revoke` returns 500 (not 400).
**Recommendation**: Define single error envelope `{success: false, error: {code: "...", message: "...", details: [...]}, timestamp: "..."}` for all platform endpoints. Shape E (STAC/OGC) is acceptable as-is.
**Effort**: M

### Theme 4: Write-Only API — Services/Outputs Gap
**Severity**: HIGH
**Affected endpoints**: `GET /api/platform/status/{id}`, `GET /api/platform/lineage/{id}`
**Intern's experience**: After approval, expected to find tile URLs, STAC links, or OGC endpoint references. Found `services: null`, `outputs: null`, `blob_path: null`, `data_access: null` everywhere. Had no idea how to actually consume the approved data.
**Architect's analysis**: These fields represent the entire value proposition — "I submitted data, it was processed, approved, and now I can consume it via these URLs." Without them, the API is a write-only interface. The TiTiler tile server and OGC Features API are fully functional but operationally disconnected from the platform status responses.
**Recommendation**: After processing completes, populate `outputs` with blob paths, `services` with tile URLs (TiTiler), OGC endpoint URLs, and STAC item references. This bridges the gap between "approved" and "consumable."
**Effort**: L

### Theme 5: Silent Parameter Ignoring
**Severity**: HIGH
**Affected endpoints**: `GET /api/platform/status` (list mode)
**Intern's experience**: Built filtering logic (`?data_type=raster`, `?status=failed`) that appeared to work with small result sets, only to realize later that parameters had no effect.
**Architect's analysis**: Tested systematically — `?data_type=raster` returns all types, `?status=failed` returns all statuses, `?offset=2` returns same results as offset=0, `?page=2` identical to page=1. This is worse than rejecting unknown params: developers build logic against a phantom API that breaks at scale.
**Recommendation**: Honor `offset`/`limit` for pagination. Implement `data_type`, `status` filters. Return 400 for unrecognized filter values. Add `total_count` and `next` link.
**Effort**: M

### Theme 6: Discoverability Gap
**Severity**: HIGH
**Affected endpoints**: Root (`/api/`), discovery
**Intern's experience**: No idea where to start. Hit `/api/` (404), `/api/docs` (404), guessed endpoints. Eventually found `GET /api/platforms` by trial and error.
**Architect's analysis**: OpenAPI spec exists at `/api/openapi.json` — well-structured with 18 endpoints. But it's not linked from anywhere. No `/api/` landing page, no Swagger UI, no cross-link to TiTiler. TiTiler itself has excellent discoverability (Swagger at `/docs`, admin at `/`). The gap is that the main API doesn't tell clients about TiTiler at all.
**Recommendation**: Add `/api/` landing page. Add `/api/docs` Swagger UI. Link TiTiler URL from platform responses. Update OpenAPI spec to match reality (version drift: spec says 0.8, app is 0.9.12.0).
**Effort**: M

### Theme 7: Response Shape Inconsistency
**Severity**: MEDIUM
**Affected endpoints**: `/approvals` vs `/status`, `/catalog/*` variants
**Intern's experience**: Same data (a release) looked completely different depending on which endpoint returned it.
**Architect's analysis**: `/approvals` returns 44-field raw database rows (45% null) with internal fields like `adf_run_id`, `workflow_id`, `node_summary`. `/status` versions array returns curated 18-field objects. A client needs two DTOs for the same entity. Additionally, 4 different catalog sub-resources with different shapes and error formats.
**Recommendation**: Create a curated release DTO with ~15 consumer-relevant fields. Use consistently across `/approvals`, `/status` versions, and catalog responses.
**Effort**: M

### Theme 8: Broken Catalog Subsystem
**Severity**: MEDIUM
**Affected endpoints**: `/api/platform/catalog/lookup`, `/api/platform/catalog/dataset/{id}`
**Intern's experience**: Both endpoints return 500 Internal Server Error.
**Architect's analysis**: Both return `OperationalError` — likely a query or connection issue in the catalog service. Cannot compare response shapes since neither endpoint works. `/catalog/assets` and `/catalog/item` return 404 (expected for test data that didn't process).
**Recommendation**: Investigate and fix the 500 errors. These are the discovery endpoints that bridge platform status to data catalog.
**Effort**: M

---

## All Findings

| # | ID | Severity | Category | Endpoint(s) | Description | Source |
|---|-----|----------|----------|-------------|-------------|--------|
| 1 | ADV-1 | CRITICAL | FLOW | `/platform/submit` (all responses) | `job_status_url` is permanently broken — 404 on every submit | Both |
| 2 | ADV-2 | CRITICAL | FLOW | `/platform/approve` | Approval succeeds on failed/unprocessed releases. `is_served=true` on non-existent data. | Both |
| 3 | ADV-3 | HIGH | ERR | All platform endpoints | 5 distinct error response shapes. Client cannot build unified error handler. | Both |
| 4 | ADV-4 | HIGH | MISS | `/platform/status/{id}` | `services` and `outputs` always null. No programmatic path from approved to consumable. | Both |
| 5 | ADV-5 | HIGH | SILENT | `/platform/status` (list) | `data_type`, `status`, `offset`, `page` filters silently ignored. | Both |
| 6 | ADV-6 | HIGH | DISC | `/api/` root | No API landing page, no `/api/docs`, OpenAPI exists but not linked. | Both |
| 7 | ADV-7 | HIGH | DISC | `/platform/status/{id}` | TiTiler URL never referenced in platform responses. Two systems operationally coupled but informationally disconnected. | Both |
| 8 | ADV-8 | HIGH | ERR | `/platform/status/{id}` | `error: null` when `job_status: "failed"`. Error details lost. `error_summary: "Unknown error"` in failures endpoint. | Both |
| 9 | ADV-9 | HIGH | ERR | `/platform/approve`, `/reject`, `/revoke` | Malformed JSON returns 500 InternalError instead of 400 ValidationError. | Architect |
| 10 | ADV-10 | MEDIUM | CON | `/platform/approvals` | 44-field raw DB row dump (45% null). Internal fields leaked. Different shape from `/status` versions. | Both |
| 11 | ADV-11 | MEDIUM | CON | `/platform/submit` | Idempotent response drops `job_type`, adds `hint`. Shape should be consistent. | Architect |
| 12 | ADV-12 | MEDIUM | ERR | `/platform/catalog/lookup`, `/catalog/dataset` | Both return 500 OperationalError. | Both |
| 13 | ADV-13 | MEDIUM | NAME | `/api/platforms` vs `/api/platform/*` | Inconsistent plural/singular root. | Architect |
| 14 | ADV-14 | MEDIUM | CON | `/platform/status/{id}` | `monitor_url` is relative, `job_status_url` is absolute (inconsistent URL format). | Architect |
| 15 | ADV-15 | MEDIUM | DOC | `/api/openapi.json` | Spec version drift (0.8 vs 0.9.12.0). `success` envelope undocumented. Missing endpoints. `PlatformResponse` schema doesn't match actual response. | Architect |
| 16 | ADV-16 | MEDIUM | SHAPE | `/platform/lineage/{id}` | `outputs: null`, `data_access: null`. Lineage endpoint has fields that are never populated. | Intern |
| 17 | ADV-17 | MEDIUM | CON | `/stac/collections` | STAC items have 0 content despite approved data. Shell collections without items. | Both |
| 18 | ADV-18 | MEDIUM | FLOW | `/platform/status` (list) vs detail | List returns 11-field flat objects, detail returns 41-field nested structure. No shared subset. | Architect |
| 19 | ADV-19 | LOW | NAME | Various | `clearance_state` field name unclear to new developers. | Intern |
| 20 | ADV-20 | LOW | CON | Various | No `Cache-Control`, `ETag`, or `Last-Modified` headers. Static resources not cacheable. | Architect |
| 21 | ADV-21 | LOW | CON | Various | No content negotiation. `Accept: text/html` returns JSON without 406. | Architect |
| 22 | ADV-22 | LOW | CON | Vector serving | OGC Features uses `table_name` IDs, TiTiler uses `geo.{table_name}` prefix. Developer must discover naming convention. | Architect |
| 23 | ADV-23 | LOW | DOC | `/api/platform/status` | No API versioning strategy (no `/v1/` prefix or `Api-Version` header). | Architect |
| 24 | ADV-24 | LOW | NAME | TiTiler | `/stac/` root returns `NoMatchFound` error. Routing bug. | Architect |
| 25 | ADV-25 | INFO | CON | Various | 404 instead of 405 for unsupported HTTP methods (Azure Functions limitation). | Architect |

---

## What Works Well

These patterns are well-designed and should be protected from regression:

1. **Idempotent submissions** (A- grade) — SHA256 request IDs, clear 200 vs 202 differentiation, helpful `hint` for overwrite. Best-in-class.
2. **STAC/OGC compliance** — STAC catalog has proper HATEOAS links (`self`, `root`, `parent`, `items`, `collection`). OGC Features has working pagination with `numberMatched`/`numberReturned`/`next`.
3. **TiTiler integration** — 92 endpoints, full Swagger UI at `/docs`, admin console at `/`. Excellent standalone DX.
4. **OpenAPI spec** — `/api/openapi.json` is well-structured with 18 endpoints documented. Just needs to be findable and current.
5. **Status detail response** — Rich nested structure with `versions` array showing full release history. Well-designed data model.
6. **Validation on submit** — Pydantic validation catches malformed input with detailed field-level errors. Good pattern (should be replicated on `/approve`/`/reject`/`/revoke`).
7. **Health endpoint** — `/api/platform/health` returns clean, useful status with version, mode, and capabilities.
8. **Failures endpoint** — `/api/platform/failures` provides clear failure timeline with `first_failure_at`/`last_failure_at` and `failure_count`. Useful operational view.

---

## Prioritized Action Plan

### P0 — Fix Before UAT

| # | Finding | Effort | Change |
|---|---------|--------|--------|
| 1 | ADV-1: `job_status_url` is dead | S | Delete `job_status_url` from all responses. Make `monitor_url` absolute. Single working URL. |
| 2 | ADV-2: Approval allows failed/pending releases | M | Add guard: `if release.processing_status != 'completed': return 409`. Block `is_served=true` on unprocessed data. |
| 3 | ADV-9: Malformed JSON returns 500 on `/approve`/`/reject`/`/revoke` | S | Already fixed in v0.9.11.11 (PRV-1). Verify still deployed. |

### P1 — Fix During UAT

| # | Finding | Effort | Change |
|---|---------|--------|--------|
| 4 | ADV-3: 5 error shapes | M | Define single error envelope for all platform endpoints. Standardize `{success, error: {code, message, details}, timestamp}`. |
| 5 | ADV-8: `error: null` on failed jobs | S | Populate from `releases.last_error` or jobs table. Fix `error_summary: "Unknown error"` in failures endpoint. |
| 6 | ADV-4: `services`/`outputs` always null | L | After processing, populate with blob paths, tile URLs, OGC endpoints, STAC references. |
| 7 | ADV-5: Silent parameter ignoring | M | Honor `offset`/`limit`. Implement `data_type`/`status` filters. Return 400 for unrecognized values. |
| 8 | ADV-6: No API discovery page | S | Add `/api/` landing page linking to OpenAPI spec. Add `/api/docs` with Swagger UI. |
| 9 | ADV-12: Catalog 500 errors | M | Fix query/connection issue in `/catalog/lookup` and `/catalog/dataset`. |

### P2 — Backlog

| # | Finding | Effort | Change |
|---|---------|--------|--------|
| 10 | ADV-10: Approvals response bloat | S | Create curated DTO (~15 fields) matching `/status` versions shape. |
| 11 | ADV-15: OpenAPI spec drift | M | Update version, add `success` envelope, document all endpoints. |
| 12 | ADV-7: TiTiler not cross-linked | S | Add `tile_server_url` to status responses. Include TiTiler reference in STAC assets. |
| 13 | ADV-13: Plural/singular naming | M | Standardize on one convention. Current `/api/platforms` + `/api/platform/*` mix is confusing. |
| 14 | ADV-11: Idempotent response shape drift | S | Include `job_type` in idempotent response. Identical shape except `message`. |
| 15 | ADV-20: No caching headers | S | Add `Cache-Control` to STAC catalog/collections. Add `ETag` to resource endpoints. |
| 16 | ADV-23: No API versioning | M | Add `/api/v1/` prefix or `Api-Version` header before partner integration. |

---

## Pipeline Chain Recommendations

For each P0/P1 finding, the recommended code-review pipeline to verify the fix:

| Finding | Pipeline | Target Files | Notes |
|---------|----------|-------------|-------|
| ADV-1 (dead job_status_url) | REFLEXION | `services/platform_response.py` | Single-file fix: delete field or register route |
| ADV-2 (approve allows failed) | COMPETE | `services/asset_approval_service.py`, `triggers/trigger_approvals.py` | Cross-file state guard. Highest-priority fix — reconfirmed in SIEGE 25, 26, TOURNAMENT 27. |
| ADV-3 (5 error shapes) | COMPETE | `triggers/trigger_approvals.py`, `triggers/trigger_platform_status.py`, `triggers/trigger_platform.py` | Cross-file error format harmonization |
| ADV-4 (services/outputs null) | COMPETE | `services/asset_approval_service.py`, `services/platform_catalog_service.py`, `infrastructure/release_repository.py` | Cross-file: populate fields at processing completion + approval |
| ADV-5 (silent param ignoring) | REFLEXION | `triggers/trigger_platform_status.py` | Single-file pagination/filter implementation |
| ADV-8 (error null on failures) | REFLEXION | `triggers/trigger_platform_status.py`, `infrastructure/release_repository.py` | Populate error from releases or jobs table |
| ADV-12 (catalog 500s) | REFLEXION | `services/platform_catalog_service.py` | Debug and fix query issue |

---

## Cross-Reference with Known Bugs

Several ADVOCATE findings correspond to bugs already tracked from prior pipeline runs:

| ADVOCATE Finding | Known Bug ID | Status | First Found |
|-----------------|-------------|--------|-------------|
| ADV-2 | SG5-1/LA-1 | **OPEN** — reconfirmed 4 times | SIEGE Run 25 (02 MAR 2026) |
| ADV-9 | PRV-1 | **FIXED** (v0.9.11.11) | TOURNAMENT Run 27 (02 MAR 2026) |
| ADV-25 | PRV-9 | **KNOWN** — Azure Functions limitation | TOURNAMENT Run 27 (02 MAR 2026) |
| ADV-5 | (New — first identified by ADVOCATE) | **OPEN** | ADVOCATE Run 31 (03 MAR 2026) |
| ADV-1 | (New — first identified by ADVOCATE) | **OPEN** | ADVOCATE Run 31 (03 MAR 2026) |

---

## Appendix: Agent Statistics

### Intern (Phase 1)

| Metric | Value |
|--------|-------|
| HTTP calls | ~45 |
| Data types tested | 3 (raster, vector, NetCDF) |
| Lifecycle steps completed | Submit→Poll→Approve→Discover (all 3 types) |
| Findings | 23 (2 CRITICAL, 4 HIGH, 11 MEDIUM, 6 LOW) |
| Top friction | `job_status_url` 404 (blocked progress for significant time) |

### Architect (Phase 2)

| Metric | Value |
|--------|-------|
| HTTP calls | 65 |
| REST dimensions graded | 12 |
| Consistency pairs analyzed | 4 |
| Service URL audits | 4 subsystems (Raster, Vector, Zarr, STAC) |
| Intern findings confirmed | 6/6 top findings (all confirmed or partially confirmed) |
| Recommendations | 15 (R-1 through R-15) |

### REST Dimension Grades

| Dimension | Grade | Notes |
|-----------|-------|-------|
| HTTP Methods | B+ | Correct POST/GET usage. 404 not 405 for unsupported methods (AF limitation). |
| Idempotency | A- | Best-in-class SHA256 deduplication. Minor shape drift on replay. |
| Status Codes | B | Mostly correct. Malformed JSON on `/approve` returns 500 (should be 400). |
| Response Bloat | C | Good list/detail split. Approvals dumps 44-field raw rows. |
| HATEOAS/Links | C | STAC/OGC excellent. Platform endpoints have near-zero navigability. |
| Naming | C- | Plural/singular mix. RPC-style verbs (acceptable if consistent). |
| Cross-Endpoint Consistency | D+ | Same entity, different shapes across endpoints. |
| Pagination | D | `/status` list broken. OGC Features works. STAC partial. |
| Versioning | D | No version prefix or header. Spec version drifted. |
| Error Format | **F** | 5 distinct shapes. Worst consistency problem. |
| Content Negotiation | **F** | Returns JSON regardless of Accept header. No 406. |
| Cacheability | **F** | No cache headers on any endpoint. |

---

*Report generated by Editor — ADVOCATE pipeline, 03 MAR 2026*
*Specialists: Intern (first impressions), Architect (structured audit)*
*Prerequisites: Schema rebuild + STAC nuke before agent execution*
