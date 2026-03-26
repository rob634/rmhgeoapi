# Security Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all actionable code-level security vulnerabilities identified in the 26 MAR 2026 security scan, excluding auth (APIM/RBAC scope).

**Architecture:** Changes are isolated to individual files — no new modules, no architectural shifts. Dependency pins are additive. Code changes are mechanical find-and-replace patterns within existing files.

**Tech Stack:** Python 3.12, psycopg 3.x (`psycopg.sql`), defusedxml (new dep), httpx, html (stdlib)

**Spec:** `docs/superpowers/specs/2026-03-26-security-remediation-design.md`

---

## Task 1: Dependency Pin Alignment (P0)

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add security section for transitive deps**

Add a new section at the end of `requirements.txt`, after the `# === External API Access ===` block:

```python
# === Security (transitive deps with known CVEs - pinned explicitly) ===
# Mirror requirements-docker.txt security pins for Function App deployment
urllib3>=2.6.3                        # CVE-2026-21441 (decompression DoS) fixed in 2.6.3
cryptography>=46.0.5                  # CVE-2026-26007 (subgroup attack) fixed in 46.0.5
certifi>=2024.7.4                     # CVE-2024-39689 (GLOBALTRUST) fixed in 2024.7.4
setuptools>=78.1.1                    # CVE-2025-47273 (path traversal) fixed in 78.1.1
```

- [ ] **Step 2: Raise floor pins for existing direct deps**

Change these three existing lines in `requirements.txt`:

| Current | New |
|---------|-----|
| `requests>=2.28.0` | `requests>=2.32.3                      # CVE-2024-35195 (verify bypass) fixed in 2.32.2` |
| `Jinja2>=3.1.0` | `Jinja2>=3.1.6                          # CVE-2025-27516 (sandbox breakout) fixed in 3.1.6` |
| `pydantic>=2.0.0` | `pydantic>=2.4.0                        # CVE-2024-3772 (ReDoS) fixed in 2.4.0` |

- [ ] **Step 3: Pin azure-functions**

Change line 6 from:
```
azure-functions
```
to:
```
azure-functions>=1.21.3               # Pin floor to prevent supply chain drift
```

(Check current installed version first: `pip show azure-functions | grep Version`)

- [ ] **Step 4: Add defusedxml to both requirements files**

Add to `requirements.txt` in the `# === Schema Validation ===` section:
```
defusedxml>=0.7.1                     # Safe XML parsing (CWE-611)
```

Add the same line to `requirements-docker.txt` in the `# === Schema Validation ===` section.

- [ ] **Step 5: Verify pip can resolve all deps**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda activate azgeo && pip install -r requirements.txt --dry-run 2>&1 | tail -5`

Expected: No conflicts. If conflicts, adjust pins.

- [ ] **Step 6: Install defusedxml**

Run: `pip install defusedxml>=0.7.1`

- [ ] **Step 7: Commit**

```bash
git add requirements.txt requirements-docker.txt
git commit -m "sec: align dependency pins with CVE fixes

Add explicit pins for urllib3, cryptography, certifi, setuptools.
Raise floor pins for requests, Jinja2, pydantic.
Pin azure-functions floor. Add defusedxml."
```

---

## Task 2: CORS Restriction (P1)

**Files:**
- Modify: `host.json:35-38`
- Modify: `ogc_features/triggers.py:192,223`

- [ ] **Step 1: Restrict CORS in host.json**

In `host.json`, replace the customHeaders block:

Old:
```json
"customHeaders": {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, HEAD, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Accept, X-Request-Id"
}
```

New:
```json
"customHeaders": {
    "Access-Control-Allow-Origin": "https://rmhazuregeo.z13.web.core.windows.net",
    "Access-Control-Allow-Methods": "GET, POST, HEAD, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Accept, X-Request-Id"
}
```

- [ ] **Step 2: Restrict CORS in OGC Features triggers**

In `ogc_features/triggers.py`, line 192, replace:
```python
response.headers['Access-Control-Allow-Origin'] = '*'
```
with:
```python
response.headers['Access-Control-Allow-Origin'] = 'https://rmhazuregeo.z13.web.core.windows.net'
```

Same change at line 223.

- [ ] **Step 3: Commit**

```bash
git add host.json ogc_features/triggers.py
git commit -m "sec: restrict CORS to known static site origin (CWE-942)"
```

---

## Task 3: Error Response Sanitization (P1)

**Files:**
- Modify: `triggers/timer_base.py:113-120`
- Modify: `triggers/health_checks/database.py:367-376`
- Modify: `triggers/stac_extract.py` (multiple catch blocks)
- Modify: `triggers/promote.py` (multiple catch blocks)
- Modify: `triggers/trigger_platform_status.py` (multiple catch blocks)

- [ ] **Step 1: Fix timer_base.py — remove traceback from return dict**

In `triggers/timer_base.py`, replace lines 113-120:

Old:
```python
        except Exception as e:
            self.logger.error(f"❌ {self.name}: Unhandled exception: {e}")
            self.logger.error(traceback.format_exc())
            return {
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc()
            }
```

New:
```python
        except Exception as e:
            self.logger.error(f"❌ {self.name}: Unhandled exception: {e}")
            self.logger.error(traceback.format_exc())
            return {
                "success": False,
                "error": "An internal error occurred. Check server logs.",
                "error_type": type(e).__name__
            }
```

- [ ] **Step 2: Fix database.py health check — remove traceback from response**

In `triggers/health_checks/database.py`, find the DuckDB error block around lines 367-376. Replace:

Old:
```python
                return {
                    "status": "error",
                    "optional": True,
                    "error": str(e)[:200],
                    "error_type": type(e).__name__,
                    "traceback": traceback.format_exc()[:500],
                    "impact": "Analytical queries and GeoParquet exports unavailable"
                }
```

New:
```python
                logger.error(f"DuckDB health check error: {e}", exc_info=True)
                return {
                    "status": "error",
                    "optional": True,
                    "error": "DuckDB health check failed. Check server logs.",
                    "impact": "Analytical queries and GeoParquet exports unavailable"
                }
```

- [ ] **Step 3: Fix stac_extract.py — sanitize all except blocks**

In `triggers/stac_extract.py`, find every pattern matching:
```python
"error": str(e),
"error_type": type(e).__name__
```

Replace each occurrence with:
```python
"error": "An internal error occurred. Check server logs.",
```

Keep the `logger.error(...)` calls that precede each return — those stay. Only the HTTP response body changes.

Search the file for all `str(e)` in return/response dicts and replace. There are approximately 6 such blocks between lines 66-306.

- [ ] **Step 4: Fix promote.py — sanitize error responses**

In `triggers/promote.py`, find every pattern where `str(e)` appears in an HTTP response dict between lines 227-576. Replace:
```python
"error": str(e)
```
with:
```python
"error": "An internal error occurred. Check server logs."
```

- [ ] **Step 5: Fix trigger_platform_status.py — sanitize error responses**

In `triggers/trigger_platform_status.py`, at lines 256, 422, and 713, replace `str(e)` in response dicts with `"An internal error occurred. Check server logs."`.

- [ ] **Step 6: Verify no regressions**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && python -c "import triggers.timer_base; import triggers.health_checks.database; import triggers.stac_extract; import triggers.promote; import triggers.trigger_platform_status; print('All imports OK')"`

- [ ] **Step 7: Commit**

```bash
git add triggers/timer_base.py triggers/health_checks/database.py triggers/stac_extract.py triggers/promote.py triggers/trigger_platform_status.py
git commit -m "sec: sanitize error responses — no str(e) or tracebacks in HTTP bodies (CWE-209)"
```

---

## Task 4: Health Check Information Redaction (P1)

**Files:**
- Modify: `triggers/health_checks/database.py:285-318`
- Modify: `triggers/health_checks/infrastructure.py:566-578`

- [ ] **Step 1: Redact database config values from health response**

In `triggers/health_checks/database.py`, find the `check_database_configuration` method around line 273. In the section starting at line 303 where `present_vars` is populated, change the logic to only record presence, not values:

Old (lines 303-305):
```python
            for var_name, var_value in required_env_vars.items():
                if var_value:
                    present_vars[var_name] = var_value
```

New:
```python
            for var_name, var_value in required_env_vars.items():
                if var_value:
                    present_vars[var_name] = True
```

Then in the `config_values` dict (lines 309-318), replace actual values with booleans:

Old:
```python
            config_values = {
                "postgis_host": config.postgis_host,
                "postgis_port": config.postgis_port,
                "postgis_user": config.postgis_user,
                "postgis_database": config.postgis_database,
                "postgis_schema": config.postgis_schema,
                "app_schema": config.app_schema,
                "key_vault_name": config.key_vault_name,
                "key_vault_database_secret": config.key_vault_database_secret,
                "postgis_password_configured": bool(config.postgis_password)
            }
```

New:
```python
            config_values = {
                "postgis_host_configured": bool(config.postgis_host),
                "postgis_port_configured": bool(config.postgis_port),
                "postgis_user_configured": bool(config.postgis_user),
                "postgis_database_configured": bool(config.postgis_database),
                "postgis_schema": config.postgis_schema,
                "app_schema": config.app_schema,
                "key_vault_configured": bool(config.key_vault_name),
                "key_vault_secret_configured": bool(config.key_vault_database_secret),
                "postgis_password_configured": bool(config.postgis_password)
            }
```

Note: `postgis_schema` and `app_schema` are kept visible — they're not secrets (just schema names like "app", "geo") and the health check needs them for diagnostics.

- [ ] **Step 2: Redact infrastructure env var values**

In `triggers/health_checks/infrastructure.py`, the `get_vars` function at line 566 already masks connection strings and keys. Strengthen it to mask all values except known-safe ones:

Old (lines 566-578):
```python
            def get_vars(var_map: dict) -> dict:
                result = {}
                for key, env_name in var_map.items():
                    value = os.environ.get(env_name)
                    if value is not None:
                        # Mask sensitive values
                        if 'connection' in key.lower() or 'key' in key.lower():
                            result[key] = f"[SET - {len(value)} chars]"
                        elif len(value) > 200:
                            result[key] = value[:200] + f"... [{len(value)} chars total]"
                        else:
                            result[key] = value
                return result
```

New:
```python
            # Safe keys whose values can be shown (non-sensitive platform metadata)
            SAFE_DISPLAY_KEYS = {
                'sku', 'compute_mode', 'slot_name', 'platform_version',
                'functions_extension_version', 'functions_worker_runtime',
                'azure_functions_environment', 'auth_enabled', 'https_only',
                'run_from_package', 'use_zip_deploy', 'scm_run_from_package',
            }

            def get_vars(var_map: dict) -> dict:
                result = {}
                for key, env_name in var_map.items():
                    value = os.environ.get(env_name)
                    if value is not None:
                        if key in SAFE_DISPLAY_KEYS:
                            result[key] = value
                        else:
                            result[key] = "[SET]"
                return result
```

- [ ] **Step 3: Commit**

```bash
git add triggers/health_checks/database.py triggers/health_checks/infrastructure.py
git commit -m "sec: redact infrastructure details from health check responses (CWE-200)"
```

---

## Task 5: XSS Escaping in Web Interfaces (P2)

**Files:**
- Modify: `web_interfaces/external_services/interface.py:307,372,599,739`
- Modify: `web_interfaces/submit_vector/interface.py:228`
- Modify: `web_interfaces/jobs/interface.py:172`
- Modify: `web_interfaces/metrics/interface.py:127,149`

- [ ] **Step 1: Fix external_services/interface.py**

Add `import html` at the top of the file (with other stdlib imports).

Then replace each unescaped `str(e)` in HTML output:

Line 307 — replace:
```python
                <p>{str(e)}</p>
```
with:
```python
                <p>{html.escape(str(e))}</p>
```

Line 372 — replace:
```python
            return f'<div class="alert alert-error">Registration failed: {str(e)}</div>'
```
with:
```python
            return f'<div class="alert alert-error">Registration failed: {html.escape(str(e))}</div>'
```

Line 599 — replace:
```python
            return f'<div class="panel-error">Error loading details: {str(e)}</div>'
```
with:
```python
            return f'<div class="panel-error">Error loading details: {html.escape(str(e))}</div>'
```

Line 739 — replace:
```python
            return f'<div class="alert alert-error">Error saving: {str(e)}</div>'
```
with:
```python
            return f'<div class="alert alert-error">Error saving: {html.escape(str(e))}</div>'
```

- [ ] **Step 2: Fix submit_vector/interface.py**

Add `import html` at the top.

Line 228 — replace:
```python
                    <p>{message}</p>
```
with:
```python
                    <p>{html.escape(message)}</p>
```

- [ ] **Step 3: Fix jobs/interface.py**

Add `import html` at the top.

Line 172 — replace:
```python
                        <p>Error loading jobs: {str(e)}</p>
```
with:
```python
                        <p>Error loading jobs: {html.escape(str(e))}</p>
```

- [ ] **Step 4: Fix metrics/interface.py**

Add `import html` at the top.

Line 127 — replace:
```python
                <p>Error loading jobs: {str(e)}</p>
```
with:
```python
                <p>Error loading jobs: {html.escape(str(e))}</p>
```

Line 149 — replace:
```python
                <p>Error: {str(e)}</p>
```
with:
```python
                <p>Error: {html.escape(str(e))}</p>
```

- [ ] **Step 5: Commit**

```bash
git add web_interfaces/external_services/interface.py web_interfaces/submit_vector/interface.py web_interfaces/jobs/interface.py web_interfaces/metrics/interface.py
git commit -m "sec: escape exception messages in HTML output (CWE-79)"
```

---

## Task 6: SQL f-string Cleanup (P2)

**Files:**
- Modify: `services/geo_orphan_detector.py:105,149`
- Modify: `triggers/health_checks/database.py:206`
- Modify: `triggers/admin/db_diagnostics.py` (8 locations)
- Modify: `triggers/admin/geo_table_operations.py:511`

- [ ] **Step 1: Fix geo_orphan_detector.py**

Add `from psycopg import sql` at the top imports.

Line 105 — replace:
```python
                                cur.execute(f'SELECT COUNT(*) FROM geo."{table_name}"')
```
with:
```python
                                cur.execute(sql.SQL('SELECT COUNT(*) FROM {}.{}').format(
                                    sql.Identifier('geo'), sql.Identifier(table_name)
                                ))
```

Line 149 — same replacement:
```python
                            cur.execute(f'SELECT COUNT(*) FROM geo."{table_name}"')
```
with:
```python
                            cur.execute(sql.SQL('SELECT COUNT(*) FROM {}.{}').format(
                                sql.Identifier('geo'), sql.Identifier(table_name)
                            ))
```

- [ ] **Step 2: Fix database.py health check**

Line 206 — replace:
```python
                            cur.execute(f"SELECT job_complete, final_stage, total_tasks, completed_tasks, task_results FROM {config.app_schema}.check_job_completion('test_job_id')")
```
with:
```python
                            cur.execute(sql.SQL("SELECT job_complete, final_stage, total_tasks, completed_tasks, task_results FROM {}.check_job_completion('test_job_id')").format(
                                sql.Identifier(config.app_schema)
                            ))
```

Ensure `from psycopg import sql` is imported at the top of the file.

- [ ] **Step 3: Fix db_diagnostics.py — all 8 locations**

Add `from psycopg import sql` at the top if not already present.

For each of the 8 `cursor.execute(f"""` calls at lines 418, 794, 856, 953, 976, 1001, 1024, 1050 — they all follow the same pattern of `{self.config.app_schema}.jobs` or `{self.config.app_schema}.tasks`.

Replace each with the `sql.SQL(...).format(sql.Identifier(...))` pattern. Example for line 794:

Old:
```python
                    cursor.execute(f"""
                        SELECT job_id, job_type, status, stage, parameters, metadata, result_data,
                               created_at, updated_at
                        FROM {self.config.app_schema}.jobs
                        WHERE job_id = %s
                    """, (job_id,))
```

New:
```python
                    cursor.execute(sql.SQL("""
                        SELECT job_id, job_type, status, stage, parameters, metadata, result_data,
                               created_at, updated_at
                        FROM {}.jobs
                        WHERE job_id = %s
                    """).format(sql.Identifier(self.config.app_schema)), (job_id,))
```

Apply the same transformation to all 8 locations. Each one interpolates `self.config.app_schema` — replace with `{}` and add `.format(sql.Identifier(self.config.app_schema))`.

**Special case — line 418**: This uses `has_schema_privilege(%s, 'CREATE')` with `self.config.app_schema` passed as a parameter (already safe). Only fix lines that use f-string interpolation of the schema into FROM/table clauses.

- [ ] **Step 4: Fix geo_table_operations.py**

Line 511 — this builds a WHERE clause from validated conditions, not from user input. The `where_clause` is constructed from hardcoded condition strings (lines 483-508) with `%s` parameters. The f-string only concatenates pre-built SQL fragments. This is safe as-is, but for consistency:

Old:
```python
                    count_sql = f"SELECT COUNT(*) FROM geo.table_catalog {where_clause}"
                    cur.execute(count_sql, params)
```

New:
```python
                    count_sql = sql.SQL("SELECT COUNT(*) FROM {}.{} ").format(
                        sql.Identifier('geo'), sql.Identifier('table_catalog')
                    ) + sql.SQL(where_clause)
                    cur.execute(count_sql, params)
```

Ensure `from psycopg import sql` is imported.

- [ ] **Step 5: Verify imports work**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && python -c "import services.geo_orphan_detector; import triggers.health_checks.database; import triggers.admin.db_diagnostics; import triggers.admin.geo_table_operations; print('All imports OK')"`

- [ ] **Step 6: Commit**

```bash
git add services/geo_orphan_detector.py triggers/health_checks/database.py triggers/admin/db_diagnostics.py triggers/admin/geo_table_operations.py
git commit -m "sec: replace SQL f-string interpolation with psycopg.sql.Identifier (CWE-89)"
```

---

## Task 7: SSRF URL Validation (P2)

**Files:**
- Modify: `services/external_service_detector.py:155-183`

- [ ] **Step 1: Add URL validation to _make_request**

In `services/external_service_detector.py`, add a validation helper and use it in `_make_request`. Add this before the `ExternalServiceDetector` class definition:

```python
import ipaddress
import socket

def _validate_url_safe(url: str) -> Optional[str]:
    """
    Validate URL is safe for server-side requests.
    Returns error message if unsafe, None if safe.
    """
    from urllib.parse import urlparse
    parsed = urlparse(url)

    # Scheme check
    if parsed.scheme not in ('http', 'https'):
        return f"Unsupported URL scheme: {parsed.scheme}"

    # Resolve hostname to check for internal IPs
    hostname = parsed.hostname
    if not hostname:
        return "URL has no hostname"

    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return f"Cannot resolve hostname: {hostname}"

    for addr_info in addr_infos:
        ip = ipaddress.ip_address(addr_info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return f"URL resolves to non-routable address"

    return None
```

- [ ] **Step 2: Wire validation into _make_request**

In `_make_request` (line 155), add the validation call at the start of the method body, before the try block:

```python
    def _make_request(
        self,
        url: str,
        method: str = 'GET',
        params: Optional[Dict] = None,
        headers: Optional[Dict] = None
    ) -> Tuple[Optional[httpx.Response], Optional[str]]:
        # Validate URL is safe for server-side request
        url_error = _validate_url_safe(url)
        if url_error:
            logger.warning(f"SSRF blocked: {url_error} for URL: {url}")
            return None, f"URL validation failed: {url_error}"

        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=False) as client:
                response = client.request(method, url, params=params, headers=headers)
                return response, None
        except httpx.TimeoutException:
            return None, "Request timeout"
        except httpx.RequestError as e:
            return None, f"Request error: {str(e)}"
        except Exception as e:
            return None, f"Unexpected error: {str(e)}"
```

Note: also changed `follow_redirects=True` to `follow_redirects=False` to prevent redirect-based SSRF bypass.

- [ ] **Step 3: Commit**

```bash
git add services/external_service_detector.py
git commit -m "sec: add SSRF URL validation — block private IPs, disable redirects (CWE-918)"
```

---

## Task 8: XML Safety with defusedxml (P2)

**Files:**
- Modify: `services/vector/converters.py:494,499,508`
- Modify: `services/external_service_detector.py:325`

- [ ] **Step 1: Fix converters.py**

In `services/vector/converters.py`, at line 494, replace:
```python
    import xml.etree.ElementTree as ET
```
with:
```python
    import defusedxml.ElementTree as ET
```

This is a local import inside the function. The `ET.parse()` and `ET.ParseError` calls at lines 499 and 508 remain unchanged — `defusedxml.ElementTree` is a drop-in replacement.

- [ ] **Step 2: Fix external_service_detector.py**

Find the import of `xml.etree.ElementTree` at the top of `services/external_service_detector.py`:
```python
import xml.etree.ElementTree as ET
```
Replace with:
```python
import defusedxml.ElementTree as ET
```

The `ET.fromstring()` call at line 325 remains unchanged.

- [ ] **Step 3: Verify defusedxml works as drop-in**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && python -c "import defusedxml.ElementTree as ET; tree = ET.fromstring('<root/>'); print('defusedxml OK:', tree.tag)"`

Expected: `defusedxml OK: root`

- [ ] **Step 4: Commit**

```bash
git add services/vector/converters.py services/external_service_detector.py
git commit -m "sec: replace xml.etree.ElementTree with defusedxml (CWE-611)"
```

---

## Task 9: Security Headers (P3)

**Files:**
- Modify: `host.json:35-38`
- Modify: `web_interfaces/__init__.py:212,225`
- Modify: `web_dashboard/__init__.py:173`
- Modify: `vector_viewer/triggers.py:92`

- [ ] **Step 1: Add security headers to host.json**

In `host.json`, add to the `customHeaders` block (which was already modified in Task 2):

```json
"customHeaders": {
    "Access-Control-Allow-Origin": "https://rmhazuregeo.z13.web.core.windows.net",
    "Access-Control-Allow-Methods": "GET, POST, HEAD, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Accept, X-Request-Id",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains"
}
```

- [ ] **Step 2: Fix CSP frame-ancestors in web_interfaces/__init__.py**

Lines 212 and 225 — replace both occurrences:

Old:
```python
"Content-Security-Policy": "frame-ancestors *"
```
New:
```python
"Content-Security-Policy": "frame-ancestors 'self' https://rmhazuregeo.z13.web.core.windows.net"
```

- [ ] **Step 3: Fix CSP in web_dashboard/__init__.py**

Line 173 — same replacement:
```python
headers={"Content-Security-Policy": "frame-ancestors *"},
```
to:
```python
headers={"Content-Security-Policy": "frame-ancestors 'self' https://rmhazuregeo.z13.web.core.windows.net"},
```

- [ ] **Step 4: Fix CSP in vector_viewer/triggers.py**

Line 92 — same replacement:
```python
"Content-Security-Policy": "frame-ancestors *"
```
to:
```python
"Content-Security-Policy": "frame-ancestors 'self' https://rmhazuregeo.z13.web.core.windows.net"
```

- [ ] **Step 5: Commit**

```bash
git add host.json web_interfaces/__init__.py web_dashboard/__init__.py vector_viewer/triggers.py
git commit -m "sec: add security headers and restrict frame-ancestors CSP (CWE-16)"
```

---

## Task 10: Documentation Secrets Cleanup (P3)

**Files:**
- Modify: `CLAUDE.md:192`
- Modify: `docs_claude/DEPLOYMENT_GUIDE.md:147,159`
- Modify: `docs_claude/ERRORS_AND_FIXES.md:1417`

- [ ] **Step 1: Replace InstrumentationKey in CLAUDE.md**

Line 192 — replace:
```
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | `InstrumentationKey=6aa0e75f-3c96...` (from rmhazuregeoapi) |
```
with:
```
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Use value from `az monitor app-insights component show` (from rmhazuregeoapi) |
```

- [ ] **Step 2: Replace in DEPLOYMENT_GUIDE.md**

Line 147 — replace the full connection string with:
```
<APPLICATIONINSIGHTS_CONNECTION_STRING from Azure Portal or az CLI>
```

Line 159 — replace the full connection string in the az CLI command with:
```
  APPLICATIONINSIGHTS_CONNECTION_STRING="$APPINSIGHTS_CONN_STRING" \
```

Add a note above the command:
```
# Get the connection string first:
# APPINSIGHTS_CONN_STRING=$(az monitor app-insights component show --app rmhazuregeoapi --resource-group rmhazure_rg --query connectionString -o tsv)
```

- [ ] **Step 3: Replace in ERRORS_AND_FIXES.md**

Line 1417 — replace the full connection string with:
```
  --settings APPLICATIONINSIGHTS_CONNECTION_STRING="$(az monitor app-insights component show --app rmhazuregeoapi --resource-group rmhazure_rg --query connectionString -o tsv)"
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md docs_claude/DEPLOYMENT_GUIDE.md docs_claude/ERRORS_AND_FIXES.md
git commit -m "sec: remove hardcoded InstrumentationKey from docs (CWE-798)"
```

---

## Task 11: Debug Log Level Cleanup (P3)

**Files:**
- Modify: `host.json:9,18,19`
- Modify: `docker.env:73`

- [ ] **Step 1: Set production-appropriate log levels in host.json**

Replace:
```json
"default": "Debug",
```
with:
```json
"default": "Information",
```

Replace:
```json
"Function.function_app": "Debug",
"Function.function_app.User": "Debug"
```
with:
```json
"Function.function_app": "Information",
"Function.function_app.User": "Information"
```

- [ ] **Step 2: Disable debug mode in docker.env**

Line 73 — replace:
```
DEBUG_MODE=true
```
with:
```
DEBUG_MODE=false
```

- [ ] **Step 3: Commit**

```bash
git add host.json docker.env
git commit -m "sec: set log levels to Information, disable DEBUG_MODE (CWE-532)"
```

---

## Task 12: DuckDB Input Validation (P2)

**Files:**
- Modify: `infrastructure/duckdb.py:237,488`

- [ ] **Step 1: Add input validation for DuckDB string interpolation**

DuckDB does not support parameterized queries for `read_parquet()` paths or `CREATE SECRET` statements, so f-string interpolation is unavoidable. Add validation to ensure inputs match expected patterns.

Near the top of `infrastructure/duckdb.py`, add a validation helper:

```python
import re

_SAFE_STORAGE_NAME = re.compile(r'^[a-z0-9]{3,24}$')
_SAFE_BLOB_PATH = re.compile(r'^[a-zA-Z0-9/_.\-*]+$')
```

Before line 237 (the `CREATE SECRET` call), add:
```python
                if not _SAFE_STORAGE_NAME.match(storage_account):
                    raise ValueError(f"Invalid storage account name: must be 3-24 lowercase alphanumeric chars")
```

Before line 488 (the `read_parquet` call), add validation of the blob_url components. In the `read_parquet_from_blob` method, after `blob_url` is constructed (line 484):
```python
        if not _SAFE_BLOB_PATH.match(blob_pattern):
            raise ValueError(f"Invalid blob pattern: contains disallowed characters")
```

- [ ] **Step 2: Commit**

```bash
git add infrastructure/duckdb.py
git commit -m "sec: validate DuckDB inputs — storage account and blob path patterns (CWE-89)"
```

---

## Execution Order Summary

| Order | Task | Priority | Estimated Time |
|-------|------|----------|----------------|
| 1 | Task 1: Dependency pins | P0 | 10 min |
| 2 | Task 2: CORS restriction | P1 | 5 min |
| 3 | Task 3: Error sanitization | P1 | 20 min |
| 4 | Task 4: Health check redaction | P1 | 10 min |
| 5 | Task 5: XSS escaping | P2 | 10 min |
| 6 | Task 6: SQL f-string cleanup | P2 | 25 min |
| 7 | Task 7: SSRF validation | P2 | 10 min |
| 8 | Task 8: defusedxml | P2 | 5 min |
| 9 | Task 12: DuckDB validation | P2 | 5 min |
| 10 | Task 9: Security headers | P3 | 10 min |
| 11 | Task 10: Doc secrets | P3 | 10 min |
| 12 | Task 11: Debug log levels | P3 | 5 min |

**Total: ~12 tasks, ~125 min estimated**
