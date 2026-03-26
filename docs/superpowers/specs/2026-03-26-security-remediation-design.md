# Security Remediation Design

**Date**: 26 MAR 2026
**Scope**: All actionable findings from SAST + SCA + Config audit
**Excluded**: Authentication on destructive endpoints (handled by APIM gating)

---

## 1. Dependency Fixes (SCA)

### 1a. Align requirements.txt with requirements-docker.txt security pins

`requirements.txt` is missing explicit pins for transitive dependencies that carry known CVEs. The Docker file already has these correct.

| Package | CVE(s) | Severity | Required Pin |
|---------|--------|----------|-------------|
| `urllib3` | CVE-2026-21441, CVE-2025-66418, CVE-2025-66471 | HIGH (CVSS 8.9) | `>=2.6.3` |
| `certifi` | CVE-2024-39689 | HIGH (CVSS 7.5) | `>=2024.7.4` |
| `setuptools` | CVE-2025-47273 | HIGH | `>=78.1.1` |
| `cryptography` | CVE-2026-26007 | MEDIUM | `>=46.0.5` |

**Files**: `requirements.txt`
**Action**: Add these four lines to the security-sensitive transitive deps section.

### 1b. Raise floor pins for direct dependencies

| Package | Current Pin | CVE | Required Pin |
|---------|------------|-----|-------------|
| `requests` | `>=2.28.0` | CVE-2024-35195 (cert verify bypass) | `>=2.32.3` |
| `Jinja2` | `>=3.1.0` | CVE-2025-27516 (sandbox breakout) | `>=3.1.6` |
| `pydantic` | `>=2.0.0` | CVE-2024-3772 (ReDoS) | `>=2.4.0` |

**Files**: `requirements.txt`
**Action**: Update existing version pins.

### 1c. Pin azure-functions

Currently completely unpinned — supply chain risk.

**Files**: `requirements.txt`
**Action**: Add floor pin matching the currently installed version.

---

## 2. SQL Injection Defence-in-Depth (CWE-89)

Most of the codebase uses `psycopg.sql.SQL` + `sql.Identifier` correctly (1,762 uses across 62 files). A handful of files use f-string interpolation for schema/table names sourced from config — not user-exploitable today, but inconsistent with project standards.

| File | Lines | Pattern |
|------|-------|---------|
| `services/geo_orphan_detector.py` | 105, 149 | `f'SELECT ... FROM geo."{table_name}"'` |
| `triggers/health_checks/database.py` | 206 | `f"SELECT ... FROM {config.app_schema}..."` |
| `triggers/admin/db_diagnostics.py` | 418, 794, 856, 953, 976, 1001, 1024, 1050 | `f"SELECT ... FROM {self.config.app_schema}..."` |
| `triggers/admin/geo_table_operations.py` | 511 | `f"SELECT COUNT(*) FROM geo.table_catalog {where_clause}"` |
| `infrastructure/duckdb.py` | 237-243, 488 | `f"... '{blob_url}'"` / `f"... '{storage_account}'"` |

**Action**: Replace f-string schema/table interpolation with `sql.SQL(...).format(schema=sql.Identifier(...))`. For DuckDB (no parameterized path support), add input validation regex.

---

## 3. Error Response Sanitization (CWE-209)

Multiple endpoints return raw `str(e)`, `type(e).__name__`, and `traceback.format_exc()` in HTTP responses. A `safe_error_response()` function already exists at `triggers/http_base.py:113` but is not used consistently.

| File | Lines | Pattern |
|------|-------|---------|
| `triggers/stac_extract.py` | 66-306 | Every except returns `str(e)` + class name |
| `triggers/health_checks/database.py` | 372-694 | `traceback.format_exc()[:500]` in response |
| `triggers/timer_base.py` | 118-119 | Full untruncated traceback in response |
| `triggers/promote.py` | 227-576 | `str(e)` as `error` field |
| `triggers/trigger_platform_status.py` | 256, 422, 713 | Raw `str(e)` |

**Action**: Replace all `str(e)` in HTTP response bodies with `safe_error_response()` pattern. Keep detailed logging server-side. Remove tracebacks from response payloads entirely.

---

## 4. Health Check Information Disclosure (CWE-200)

Health and diagnostic endpoints return actual infrastructure values (hostnames, usernames, ports, schema names, Key Vault names, auth token metadata).

| File | Lines | Exposed Data |
|------|-------|-------------|
| `triggers/health_checks/database.py` | 285-318 | `POSTGIS_HOST`, `POSTGIS_USER`, `POSTGIS_DATABASE`, `POSTGIS_PORT`, Key Vault name |
| `triggers/health_checks/infrastructure.py` | 540-578 | Azure env vars, resource group, region, storage config |
| `triggers/probes.py` | 278-306 | Token TTL, freshness status for all cached tokens |
| `docker_service.py` | 1468-1477 | Token metadata |

**Action**: Return boolean connectivity status and pass/fail for each check. Move actual values to server-side debug logging only.

---

## 5. CORS Restriction (CWE-942)

Wildcard `Access-Control-Allow-Origin: *` is set in two places:

| File | Lines |
|------|-------|
| `host.json` | 36-39 |
| `ogc_features/triggers.py` | 192, 223 |

**Action**: Replace `*` with explicit allowed origins:
- `https://rmhazuregeo.z13.web.core.windows.net` (static site)
- `http://localhost:*` (dev only, gated on environment)

---

## 6. XSS in Web Interfaces (CWE-79)

Exception messages rendered in HTML without `html.escape()`. The base handler at `web_interfaces/__init__.py:277` already does this correctly — individual interfaces don't.

| File | Lines |
|------|-------|
| `web_interfaces/external_services/interface.py` | 307, 372, 599, 739 |
| `web_interfaces/submit_vector/interface.py` | 228 |
| `web_interfaces/jobs/interface.py` | 172 |
| `web_interfaces/metrics/interface.py` | 127, 149 |

**Action**: Wrap all `str(e)` in HTML responses with `html.escape(str(e))`.

---

## 7. SSRF via External Service Registration (CWE-918)

`services/external_service_detector.py:83-183` — User-provided URL passed to `httpx.Client().request(method, url, follow_redirects=True)` without validation.

**Action**: Add URL validation helper:
1. Allow only `http://` and `https://` schemes
2. Resolve DNS, block private/internal IP ranges (10.x, 172.16-31.x, 192.168.x, 127.x, 169.254.x)
3. Disable `follow_redirects` or validate redirect targets

---

## 8. XXE / Entity Expansion DoS (CWE-611)

`services/vector/converters.py:499,508` — `ET.parse()` on user-uploaded KML files. Python's `ElementTree` doesn't resolve external entities, but is vulnerable to billion laughs (entity expansion) on older Python.

**Action**: Replace `xml.etree.ElementTree` with `defusedxml.ElementTree` in `converters.py` and `services/external_service_detector.py:325`. Add `defusedxml` to both requirements files.

---

## 9. Security Headers (CWE-16)

No `X-Content-Type-Options`, `Strict-Transport-Security`, or `X-Frame-Options` headers. CSP is `frame-ancestors *` (clickjacking risk).

| File | Lines | Current |
|------|-------|---------|
| `web_interfaces/__init__.py` | 212, 225 | `frame-ancestors *` |
| `web_dashboard/__init__.py` | 173 | `frame-ancestors *` |
| `vector_viewer/triggers.py` | 92 | `frame-ancestors *` |

**Action**: Add security headers to `host.json` custom headers and to FastAPI/web interface response middleware:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: SAMEORIGIN`
- `Strict-Transport-Security: max-age=31536000; includeSubDomains` (HTTPS only)
- `Content-Security-Policy: frame-ancestors 'self' https://rmhazuregeo.z13.web.core.windows.net`

---

## 10. Documentation Secrets Cleanup (CWE-798)

Application Insights `InstrumentationKey` committed in documentation files.

| File | Line |
|------|------|
| `CLAUDE.md` | 192 |
| `docs_claude/DEPLOYMENT_GUIDE.md` | 147 |
| `docs_claude/ERRORS_AND_FIXES.md` | 1417 |

**Action**: Replace with `<your-instrumentation-key>` placeholders. Reference environment variable instead.

---

## 11. Debug Logging in Production Config (CWE-532)

| File | Setting | Current |
|------|---------|---------|
| `host.json` | `logging.logLevel.default` | `"Debug"` |
| `docker.env` | `DEBUG_MODE` | `true` |

**Action**: Set `host.json` log level to `"Information"`. Set `DEBUG_MODE=false` in `docker.env`. Add comment noting these should be `Debug`/`true` only for local development.

---

## Findings NOT Addressed (by design)

| Finding | Reason |
|---------|--------|
| C1 — Anonymous auth on all endpoints | Will be gated by APIM |
| C2 — CORS + no auth combo | Auth portion handled by APIM; CORS restriction IS addressed (item 5) |
| L1 — PGPASSWORD in subprocess env | Inherent to pypgstac CLI |
| L2 — MD5 for advisory locks | Not used for security |
| L6 — No CORS on Docker worker | Not browser-facing |
| Rate limiting (M4) | Will be handled by APIM |

---

## Implementation Priority

| Priority | Items | Effort |
|----------|-------|--------|
| P0 — Do now | 1a, 1b, 1c (dependency pins) | 15 min |
| P1 — Same sprint | 3 (error sanitization), 4 (info disclosure), 5 (CORS) | 2-3 hours |
| P2 — Next sprint | 2 (SQL f-strings), 6 (XSS), 7 (SSRF), 8 (XXE) | 3-4 hours |
| P3 — Backlog | 9 (security headers), 10 (doc secrets), 11 (debug logging) | 1 hour |
