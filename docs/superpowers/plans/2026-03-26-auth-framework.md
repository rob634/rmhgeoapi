# Auth Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a toggle-able auth framework — browser-side token injection to eliminate 401s when Easy Auth is enabled, plus Python RBAC decorator pattern for future role-gated endpoints.

**Architecture:** Two independent layers. Layer 1: JavaScript fetch wrapper in `BaseInterface` that transparently attaches Easy Auth tokens to same-origin API calls (no-op when Easy Auth absent). Layer 2: Python `@require_role()` decorator that reads Easy Auth identity headers and gates endpoints by role (no-op when `AUTH_GATES_ENABLED=false`). Both layers degrade gracefully — the app works identically with or without Easy Auth.

**Tech Stack:** Azure Easy Auth (platform-level), HTMX 1.9.10, Azure Functions Python v2 (Blueprint pattern)

---

## File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| `web_interfaces/base.py` | BaseInterface — shared HTML/CSS/JS for all 41 interfaces | Modify: add auth JS to `COMMON_JS` and `HTMX_JS` |
| `infrastructure/auth/rbac.py` | RBAC module — identity extraction + role decorator | Create |
| `infrastructure/auth/__init__.py` | Auth package exports | Modify: add RBAC exports |
| `config/defaults.py` | Default values | Modify: add `AuthDefaults` |
| `config/auth_config.py` | Auth config (BaseModel, matches all other configs) | Create |
| `config/app_config.py` | Main config composition | Modify: compose `AuthConfig` |
| `config/__init__.py` | Config exports | Modify: export `AuthConfig` |
| `triggers/admin/admin_db.py` | DB admin blueprint | Modify: wire proof-of-concept gate |
| `tests/test_rbac.py` | RBAC unit tests | Create |

---

## Context for Implementers

### How Easy Auth Works (Zero Custom Code in Python)

Azure Easy Auth is **middleware at the App Service level** — it intercepts HTTP requests before they reach function code.

**Browser flow:** User visits the app → Easy Auth redirects to Microsoft login → user authenticates → Easy Auth stores token in session (Token Store) → user can retrieve their token from `/.auth/me`.

**After authentication**, Easy Auth injects identity headers into every request that reaches function code:
```
X-MS-CLIENT-PRINCIPAL-NAME = "Robert Harrison"
X-MS-CLIENT-PRINCIPAL-ID = "abc-123-def"
X-MS-CLIENT-PRINCIPAL-IDP = "aad"
X-MS-CLIENT-PRINCIPAL = "<base64 JSON blob with claims including roles>"
```

**When Easy Auth is NOT enabled** (dev, local, current state): these headers are absent, `/.auth/me` returns 404.

### The 401 Problem

The admin UI loads fine (HTML page from `/api/interface/*`). But JavaScript `fetch()` calls to `/api/platform/*` go out with no `Authorization` header. Easy Auth blocks them. Fix: retrieve the token from `/.auth/me` and attach it.

### Key Injection Points

- `BaseInterface.COMMON_JS` (line ~1162 in `base.py`): Global JS loaded by ALL 41 interfaces
- `BaseInterface.HTMX_JS` (line ~1849 in `base.py`): HTMX config and event handlers
- `BaseInterface.wrap_html()` (line ~2053 in `base.py`): Assembles the HTML document
- `<body hx-headers='{"Accept": "application/json"}'>` (line ~2120): Default HTMX headers

### Existing `fetch()` Calls (40+ across 12 interfaces)

Most use `${API_BASE_URL}/api/...` — same-origin or orchestrator URL. Some call external services (TiTiler, TiPG). Auth headers must ONLY be added to same-origin `/api/*` calls, never leaked to external services.

---

## Task 1: Auth Token Manager (JavaScript in BaseInterface)

**Files:**
- Modify: `web_interfaces/base.py:1162-1170` (COMMON_JS — add auth block before existing code)

**What this does:** Adds a transparent `window.fetch` wrapper that:
1. On first API call, tries `/.auth/me` to get the token (cached for session)
2. If token exists, injects `Authorization: Bearer <token>` into same-origin `/api/*` requests
3. If `/.auth/me` fails (no Easy Auth): no-op, all fetch calls work as before
4. On 401 response: clears cached token, re-fetches from `/.auth/me`, retries once

**Why wrap `window.fetch` instead of replacing individual calls:** There are 40+ `fetch()` calls across 12 interfaces. Wrapping the global avoids touching every file and ensures new code automatically gets auth.

- [ ] **Step 1: Add auth token IIFE to COMMON_JS**

Insert this block at the very start of `COMMON_JS` (before the `API_BASE_URL` line at ~1168):

```javascript
// ============================================================
// AUTH TOKEN MANAGER (26 MAR 2026)
// ============================================================
// Transparent auth for Easy Auth environments.
// Wraps window.fetch to inject Bearer token on same-origin /api/* calls.
// No-op when Easy Auth is not enabled (dev/local).
// HTMX uses XMLHttpRequest (not fetch), so the token is also exposed
// synchronously via window._getCachedToken() for the configRequest hook.

(function() {
    let _authToken = null;
    let _authPromise = null;  // Deduplicates concurrent calls
    const _originalFetch = window.fetch.bind(window);

    function _isSameOriginApi(url) {
        // Only attach auth to /api/* paths on same origin or API_BASE_URL
        // Note: when API_BASE_URL points to the orchestrator (platform mode),
        // we intentionally send the token there — orchestrator is internal
        // and does not have its own Easy Auth (token is harmlessly ignored).
        const str = String(url);
        if (str.startsWith('/api/')) return true;
        try {
            const parsed = new URL(str);
            const origin = window.API_BASE_URL || window.location.origin;
            return parsed.origin === new URL(origin, window.location.origin).origin
                   && parsed.pathname.startsWith('/api/');
        } catch (e) {
            return false;
        }
    }

    async function _fetchAuthToken() {
        // Promise-based deduplication: concurrent callers share one flight
        if (_authPromise) return _authPromise;
        _authPromise = (async () => {
            try {
                const resp = await _originalFetch('/.auth/me');
                if (resp.ok) {
                    const data = await resp.json();
                    if (Array.isArray(data) && data[0]) {
                        // Prefer id_token; fall back to access_token
                        _authToken = data[0].id_token || data[0].access_token || null;
                        if (_authToken) {
                            console.log('[Auth] Token acquired from /.auth/me');
                        }
                    }
                }
            } catch (e) {
                // No Easy Auth — silent, expected in dev/local
            }
            return _authToken;
        })();
        return _authPromise;
    }

    // Expose for HTMX (synchronous read) and diagnostics
    window._getAuthToken = _fetchAuthToken;          // async — returns Promise
    window._getCachedToken = function() { return _authToken; };  // sync — for HTMX configRequest
    window._clearAuthToken = function() { _authPromise = null; _authToken = null; };
    window._hasAuth = function() { return _authToken !== null; };

    // Eager fetch on page load so token is cached before first HTMX request
    _fetchAuthToken();

    window.fetch = async function(url, options) {
        options = options || {};
        if (_isSameOriginApi(url)) {
            const token = await _fetchAuthToken();
            if (token) {
                const headers = new Headers(options.headers || {});
                if (!headers.has('Authorization')) {
                    headers.set('Authorization', 'Bearer ' + token);
                }
                options = { ...options, headers };
            }
        }

        const response = await _originalFetch(url, options);

        // 401 retry: token may have expired (~1 hour). Refresh and retry once.
        if (response.status === 401 && _authToken && _isSameOriginApi(url)) {
            console.log('[Auth] 401 received, refreshing token...');
            window._clearAuthToken();
            const newToken = await _fetchAuthToken();
            if (newToken) {
                const retryHeaders = new Headers(options.headers || {});
                retryHeaders.delete('Authorization');
                retryHeaders.set('Authorization', 'Bearer ' + newToken);
                return _originalFetch(url, { ...options, headers: retryHeaders });
            }
        }

        return response;
    };
})();
```

- [ ] **Step 2: Verify no interfaces break**

Run the app locally (no Easy Auth) and confirm:
- `/api/interface/platform` loads, health check fetch works (no auth needed locally)
- `/api/interface/submit` loads, HTMX fragments work
- Browser console shows no errors from the auth IIFE (`_authChecked = true`, no token)

```bash
# Start local function app
cd /Users/robertharrison/python_builds/rmhgeoapi
func start
# Visit http://localhost:7071/api/interface/platform
# Check browser console for "[Auth]" messages — should see nothing (no Easy Auth)
```

- [ ] **Step 3: Commit**

```bash
git add web_interfaces/base.py
git commit -m "feat: transparent auth token injection for Easy Auth environments

Wraps window.fetch to inject Bearer token from /.auth/me on
same-origin /api/* calls. No-op when Easy Auth is not enabled.
Covers all 41 web interfaces without modifying individual files."
```

---

## Task 2: HTMX Auth Header Injection

**Files:**
- Modify: `web_interfaces/base.py:1872` (HTMX_JS — add configRequest handler)

**What this does:** HTMX makes requests independently of `window.fetch` — it uses XMLHttpRequest internally. We need a separate hook via the `htmx:configRequest` event to inject the auth header.

- [ ] **Step 1: Add HTMX configRequest auth hook**

In `HTMX_JS`, add this handler right after the existing `htmx:beforeRequest` handler (after line ~1875):

```javascript
// Auth header injection for HTMX requests (26 MAR 2026)
// HTMX uses XMLHttpRequest (not window.fetch) and fires configRequest
// SYNCHRONOUSLY — the handler must not be async. We read the cached
// token that was eagerly fetched on page load (see Task 1 IIFE).
document.body.addEventListener('htmx:configRequest', function(evt) {
    if (typeof window._getCachedToken === 'function') {
        const token = window._getCachedToken();
        if (token) {
            evt.detail.headers['Authorization'] = 'Bearer ' + token;
        }
    }
});
```

- [ ] **Step 2: Verify HTMX partials still work locally**

```bash
# Start local function app
func start
# Visit http://localhost:7071/api/interface/submit
# Use the submit form — HTMX partials should render without errors
# Visit http://localhost:7071/api/interface/platform
# Use the status lookup form — HTMX POST should work
```

- [ ] **Step 3: Commit**

```bash
git add web_interfaces/base.py
git commit -m "feat: HTMX auth header injection via configRequest event

HTMX uses XMLHttpRequest internally, not window.fetch, so the
fetch wrapper from Task 1 doesn't cover it. This hooks
htmx:configRequest to inject Bearer token on HTMX requests."
```

---

## Task 3: Python RBAC Module

**Files:**
- Create: `infrastructure/auth/rbac.py`
- Modify: `infrastructure/auth/__init__.py`
- Create: `config/auth_config.py`
- Modify: `config/defaults.py`
- Modify: `config/app_config.py`
- Modify: `config/__init__.py`
- Create: `tests/test_rbac.py`

**What this does:** Provides `get_caller_identity()` to extract who's calling from Easy Auth headers, and `@require_role()` decorator to gate endpoints. Everything is toggle-able via `AUTH_GATES_ENABLED` env var (default: `false`).

### Step 3a: Config

- [ ] **Step 3a.1: Add AuthDefaults to config/defaults.py**

Add this class alongside the other defaults classes:

```python
class AuthDefaults:
    """Auth/RBAC defaults."""
    AUTH_GATES_ENABLED = False  # When False, @require_role is a no-op
```

- [ ] **Step 3a.2: Create config/auth_config.py**

```python
"""
Auth/RBAC Configuration.

Controls whether role-based access gates are enforced.
When AUTH_GATES_ENABLED=false (default), all @require_role decorators are no-ops.

Usage:
    from config import get_config
    config = get_config()
    if config.auth.gates_enabled:
        # enforce role checks
"""

import os
from pydantic import BaseModel, Field
from .defaults import AuthDefaults, parse_bool


class AuthConfig(BaseModel):
    """Auth/RBAC configuration. Uses BaseModel to match all other config classes."""

    gates_enabled: bool = Field(default=AuthDefaults.AUTH_GATES_ENABLED)

    @classmethod
    def from_environment(cls) -> 'AuthConfig':
        return cls(
            gates_enabled=parse_bool(
                os.environ.get('AUTH_GATES_ENABLED', str(AuthDefaults.AUTH_GATES_ENABLED))
            ),
        )

    def debug_dict(self) -> dict:
        return {
            'gates_enabled': self.gates_enabled,
        }
```

- [ ] **Step 3a.3: Compose AuthConfig into AppConfig**

In `config/app_config.py`, add `auth: AuthConfig` field alongside the other domain configs:

```python
from .auth_config import AuthConfig

# In AppConfig class:
auth: AuthConfig = field(default_factory=AuthConfig)

# In from_environment():
auth=AuthConfig.from_environment(),
```

- [ ] **Step 3a.4: Export AuthConfig from config/__init__.py**

```python
from .auth_config import AuthConfig

# Add to __all__:
'AuthConfig',
```

- [ ] **Step 3a.5: Add auth to debug_config() in config/__init__.py**

```python
# In debug_config() dict:
'auth': config.auth.debug_dict(),
```

- [ ] **Step 3a.6: Commit config changes**

```bash
git add config/defaults.py config/auth_config.py config/app_config.py config/__init__.py
git commit -m "feat: AuthConfig with AUTH_GATES_ENABLED toggle (default: false)"
```

### Step 3b: RBAC Module

- [ ] **Step 3b.1: Write failing tests**

Create `tests/test_rbac.py`:

```python
"""Tests for infrastructure.auth.rbac module."""

import base64
import json
import pytest
from unittest.mock import MagicMock, patch


class TestGetCallerIdentity:
    """Test get_caller_identity() header extraction."""

    def test_returns_anonymous_when_no_headers(self):
        """No Easy Auth headers → anonymous identity."""
        from infrastructure.auth.rbac import get_caller_identity
        req = MagicMock()
        req.headers = {}

        identity = get_caller_identity(req)

        assert identity.is_anonymous is True
        assert identity.name is None
        assert identity.roles == []

    def test_extracts_identity_from_easy_auth_headers(self):
        """Easy Auth headers present → populated identity."""
        from infrastructure.auth.rbac import get_caller_identity

        claims = {
            "claims": [
                {"typ": "name", "val": "Robert Harrison"},
                {"typ": "roles", "val": "GeoAdmin"},
                {"typ": "preferred_username", "val": "rharrison1@worldbankgroup.org"},
            ]
        }
        principal_b64 = base64.b64encode(json.dumps(claims).encode()).decode()

        req = MagicMock()
        req.headers = {
            'X-MS-CLIENT-PRINCIPAL-NAME': 'Robert Harrison',
            'X-MS-CLIENT-PRINCIPAL-ID': 'abc-123',
            'X-MS-CLIENT-PRINCIPAL-IDP': 'aad',
            'X-MS-CLIENT-PRINCIPAL': principal_b64,
        }

        identity = get_caller_identity(req)

        assert identity.is_anonymous is False
        assert identity.name == 'Robert Harrison'
        assert identity.principal_id == 'abc-123'
        assert 'GeoAdmin' in identity.roles

    def test_handles_malformed_principal_blob(self):
        """Bad base64 blob → falls back to header-only identity."""
        from infrastructure.auth.rbac import get_caller_identity
        req = MagicMock()
        req.headers = {
            'X-MS-CLIENT-PRINCIPAL-NAME': 'Test User',
            'X-MS-CLIENT-PRINCIPAL-ID': 'xyz-789',
            'X-MS-CLIENT-PRINCIPAL': 'not-valid-base64!!!',
        }

        identity = get_caller_identity(req)

        assert identity.is_anonymous is False
        assert identity.name == 'Test User'
        assert identity.roles == []  # Could not parse roles from blob


class TestRequireRole:
    """Test @require_role() decorator."""

    @patch('infrastructure.auth.rbac._get_auth_config')
    def test_passes_through_when_gates_disabled(self, mock_config):
        """AUTH_GATES_ENABLED=false → decorator is no-op."""
        from infrastructure.auth.rbac import require_role
        mock_config.return_value = MagicMock(gates_enabled=False)

        @require_role('GeoAdmin')
        def handler(req):
            return 'ok'

        req = MagicMock()
        req.headers = {}  # No auth headers
        result = handler(req)
        assert result == 'ok'

    @patch('infrastructure.auth.rbac._get_auth_config')
    def test_returns_403_when_role_missing(self, mock_config):
        """Gates enabled + role missing → 403. Response must NOT leak role names."""
        from infrastructure.auth.rbac import require_role
        mock_config.return_value = MagicMock(gates_enabled=True)

        @require_role('GeoAdmin')
        def handler(req):
            return 'ok'

        req = MagicMock()
        req.headers = {
            'X-MS-CLIENT-PRINCIPAL-NAME': 'No-Role User',
            'X-MS-CLIENT-PRINCIPAL-ID': 'abc',
        }
        result = handler(req)
        assert result.status_code == 403
        # Must not contain role names (information disclosure)
        body = result.get_body().decode() if hasattr(result, 'get_body') else str(result)
        assert 'GeoAdmin' not in body

    @patch('infrastructure.auth.rbac._get_auth_config')
    def test_passes_when_role_present(self, mock_config):
        """Gates enabled + role present → passes through."""
        from infrastructure.auth.rbac import require_role
        mock_config.return_value = MagicMock(gates_enabled=True)

        claims = {
            "claims": [
                {"typ": "roles", "val": "GeoAdmin"},
            ]
        }
        principal_b64 = base64.b64encode(json.dumps(claims).encode()).decode()

        @require_role('GeoAdmin')
        def handler(req):
            return 'ok'

        req = MagicMock()
        req.headers = {
            'X-MS-CLIENT-PRINCIPAL-NAME': 'Admin User',
            'X-MS-CLIENT-PRINCIPAL-ID': 'abc',
            'X-MS-CLIENT-PRINCIPAL': principal_b64,
        }
        result = handler(req)
        assert result == 'ok'

    @patch('infrastructure.auth.rbac._get_auth_config')
    def test_returns_401_when_anonymous_and_gates_enabled(self, mock_config):
        """Gates enabled + no identity → 401."""
        from infrastructure.auth.rbac import require_role
        mock_config.return_value = MagicMock(gates_enabled=True)

        @require_role('GeoAdmin')
        def handler(req):
            return 'ok'

        req = MagicMock()
        req.headers = {}
        result = handler(req)
        assert result.status_code == 401

    @patch('infrastructure.auth.rbac._get_auth_config')
    def test_multi_role_any_match_passes(self, mock_config):
        """Gates enabled + caller has one of multiple allowed roles → passes."""
        from infrastructure.auth.rbac import require_role
        mock_config.return_value = MagicMock(gates_enabled=True)

        claims = {
            "claims": [
                {"typ": "roles", "val": "DataManager"},
            ]
        }
        principal_b64 = base64.b64encode(json.dumps(claims).encode()).decode()

        @require_role('GeoAdmin', 'DataManager')
        def handler(req):
            return 'ok'

        req = MagicMock()
        req.headers = {
            'X-MS-CLIENT-PRINCIPAL-NAME': 'Data User',
            'X-MS-CLIENT-PRINCIPAL-ID': 'abc',
            'X-MS-CLIENT-PRINCIPAL': principal_b64,
        }
        result = handler(req)
        assert result == 'ok'
```

- [ ] **Step 3b.2: Run tests to verify they fail**

```bash
cd /Users/robertharrison/python_builds/rmhgeoapi
conda activate azgeo
python -m pytest tests/test_rbac.py -v
```

Expected: `ModuleNotFoundError: No module named 'infrastructure.auth.rbac'`

- [ ] **Step 3b.3: Implement rbac.py**

Create `infrastructure/auth/rbac.py`:

```python
# ============================================================================
# RBAC MODULE — Role-Based Access Control
# ============================================================================
# STATUS: Infrastructure — identity extraction + role gate decorator
# PURPOSE: Read Easy Auth headers, gate endpoints by role
# CREATED: 26 MAR 2026
# EXPORTS: CallerIdentity, get_caller_identity, require_role
# DEPENDENCIES: azure.functions (for HttpResponse in decorator)
# ============================================================================
"""
RBAC Module for Azure Easy Auth.

Extracts caller identity from Easy Auth headers (injected at platform level)
and provides a @require_role() decorator for gating endpoints.

Toggle: AUTH_GATES_ENABLED env var (default: false).
When false, @require_role is a complete no-op — zero overhead.

Usage:
    from infrastructure.auth.rbac import get_caller_identity, require_role

    # Extract identity (always works — returns anonymous if no headers)
    identity = get_caller_identity(req)
    logger.info(f"Request from: {identity.name or 'anonymous'}")

    # Gate an endpoint (only enforced when AUTH_GATES_ENABLED=true)
    @require_role('GeoAdmin')
    def handle_rebuild(req):
        ...
"""

import base64
import functools
import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional

import azure.functions as func

logger = logging.getLogger(__name__)


@dataclass
class CallerIdentity:
    """Identity extracted from Easy Auth headers."""

    name: Optional[str] = None
    principal_id: Optional[str] = None
    identity_provider: Optional[str] = None
    roles: List[str] = field(default_factory=list)
    email: Optional[str] = None

    @property
    def is_anonymous(self) -> bool:
        return self.principal_id is None


def get_caller_identity(req) -> CallerIdentity:
    """
    Extract caller identity from Easy Auth headers.

    Easy Auth injects these headers after token validation:
        X-MS-CLIENT-PRINCIPAL-NAME — display name
        X-MS-CLIENT-PRINCIPAL-ID — object ID (GUID)
        X-MS-CLIENT-PRINCIPAL-IDP — identity provider ("aad")
        X-MS-CLIENT-PRINCIPAL — base64 JSON blob with all claims

    Returns anonymous identity if headers are absent (no Easy Auth).
    """
    headers = req.headers

    name = headers.get('X-MS-CLIENT-PRINCIPAL-NAME')
    principal_id = headers.get('X-MS-CLIENT-PRINCIPAL-ID')
    idp = headers.get('X-MS-CLIENT-PRINCIPAL-IDP')

    if not principal_id:
        return CallerIdentity()

    # Parse roles from the base64 principal blob
    roles = []
    email = None
    principal_blob = headers.get('X-MS-CLIENT-PRINCIPAL', '')
    if principal_blob:
        try:
            decoded = json.loads(base64.b64decode(principal_blob))
            claims = decoded.get('claims', [])
            for claim in claims:
                if claim.get('typ') == 'roles':
                    roles.append(claim['val'])
                elif claim.get('typ') in ('preferred_username', 'email'):
                    email = claim['val']
        except Exception as e:
            logger.debug(f"Could not parse X-MS-CLIENT-PRINCIPAL blob: {e}")

    return CallerIdentity(
        name=name,
        principal_id=principal_id,
        identity_provider=idp,
        roles=roles,
        email=email,
    )


def _get_auth_config():
    """Get auth config — separated for testability."""
    from config import get_config
    return get_config().auth


def require_role(*roles: str):
    """
    Decorator to gate an endpoint by one or more roles (caller needs ANY one).

    When AUTH_GATES_ENABLED=false (default): complete no-op, zero overhead.
    When AUTH_GATES_ENABLED=true:
        - Anonymous caller → 401
        - Caller without any required role → 403
        - Caller with at least one required role → passes through

    Usage:
        @require_role('GeoAdmin')
        def handle_rebuild(req: func.HttpRequest) -> func.HttpResponse:
            ...

        @require_role('GeoAdmin', 'DataManager')
        def handle_approve(req: func.HttpRequest) -> func.HttpResponse:
            ...

    The decorated function must accept an HttpRequest as its first argument.
    """
    required_roles = set(roles)

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(req, *args, **kwargs):
            config = _get_auth_config()

            if not config.gates_enabled:
                return fn(req, *args, **kwargs)

            identity = get_caller_identity(req)

            if identity.is_anonymous:
                logger.warning(
                    f"[RBAC] 401 — anonymous request to {fn.__name__} "
                    f"(requires: {required_roles})"
                )
                return func.HttpResponse(
                    json.dumps({
                        'error': 'Authentication required',
                        'detail': 'This endpoint requires authentication. '
                                  'Please sign in or provide a valid Bearer token.',
                    }),
                    status_code=401,
                    mimetype='application/json',
                )

            caller_roles = set(identity.roles)
            if not caller_roles & required_roles:
                # Log the details server-side but do NOT expose role names to the client
                logger.warning(
                    f"[RBAC] 403 — {identity.name} ({identity.principal_id}) "
                    f"has roles {identity.roles}, needs one of {required_roles} "
                    f"for {fn.__name__}"
                )
                return func.HttpResponse(
                    json.dumps({
                        'error': 'Insufficient permissions',
                        'detail': 'You do not have permission to access this endpoint.',
                    }),
                    status_code=403,
                    mimetype='application/json',
                )

            logger.info(
                f"[RBAC] Authorized: {identity.name} → {fn.__name__}"
            )
            return fn(req, *args, **kwargs)
        return wrapper
    return decorator
```

- [ ] **Step 3b.4: Update infrastructure/auth/__init__.py exports**

Add RBAC imports to the end of `infrastructure/auth/__init__.py`:

```python
# RBAC — Role-Based Access Control (26 MAR 2026)
from .rbac import CallerIdentity, get_caller_identity, require_role

# Add to __all__:
"CallerIdentity",
"get_caller_identity",
"require_role",
```

- [ ] **Step 3b.5: Run tests**

```bash
python -m pytest tests/test_rbac.py -v
```

Expected: All 6 tests pass.

- [ ] **Step 3b.6: Commit**

```bash
git add infrastructure/auth/rbac.py infrastructure/auth/__init__.py tests/test_rbac.py
git commit -m "feat: RBAC module — get_caller_identity + @require_role decorator

Reads Easy Auth X-MS-CLIENT-PRINCIPAL-* headers to extract caller
identity and roles. @require_role decorator gates endpoints when
AUTH_GATES_ENABLED=true (default: false = no-op). 6 tests."
```

---

## Task 4: Wire Up Proof-of-Concept Gate

**Files:**
- Modify: `triggers/admin/db_maintenance.py` (the handler class)

**What this does:** Adds `@require_role('GeoAdmin')` to the destructive `action=rebuild` path as a proof-of-concept. Since `AUTH_GATES_ENABLED` defaults to `false`, this is a no-op until explicitly enabled. Demonstrates the pattern for future endpoints.

- [ ] **Step 1: Add role gate to rebuild handler**

In `triggers/admin/db_maintenance.py`, find `handle_maintenance` method (~line 181). The method dispatches to sub-handlers based on `action` param. Add the gate to the rebuild path:

```python
from infrastructure.auth.rbac import get_caller_identity

# Inside handle_maintenance, at the top of the method:
identity = get_caller_identity(req)
if identity.is_anonymous:
    logger.info(f"[Maintenance] Anonymous request: action={action}")
else:
    logger.info(f"[Maintenance] Request from: {identity.name} roles={identity.roles}")
```

This is **audit-only** — logs who called it, doesn't block. The `@require_role` decorator should be applied at the blueprint route level when gates are turned on. For now, just demonstrate the identity extraction.

- [ ] **Step 2: Test locally**

```bash
func start
# Call rebuild endpoint (should work — no gates enforced)
curl -X POST "http://localhost:7071/api/dbadmin/maintenance?action=ensure&confirm=yes"
# Check logs — should see "[Maintenance] Anonymous request"
```

- [ ] **Step 3: Commit**

```bash
git add triggers/admin/db_maintenance.py
git commit -m "feat: audit caller identity on dbadmin/maintenance (proof-of-concept)

Logs caller identity from Easy Auth headers on maintenance requests.
No blocking — demonstrates the RBAC pattern for future role gates."
```

---

## Task 5: Integration Verification

**Files:** None — testing only.

**What this does:** Verifies the complete auth flow works end-to-end on Azure (where Easy Auth can be enabled).

- [ ] **Step 1: Deploy to Azure**

```bash
./deploy.sh orchestrator
```

- [ ] **Step 2: Test without Easy Auth (current state)**

```bash
# All should work as before
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/platform/health
# Browser: visit /api/interface/platform — should load, no console errors
```

- [ ] **Step 3: Enable Easy Auth on rmhazuregeoapi (Azure Portal)**

This step is manual (Azure Portal):
1. Go to `rmhazuregeoapi` → Authentication
2. Add identity provider → Microsoft
3. Select existing app registration
4. Set "Restrict access" to "Require authentication"
5. Set "Unauthenticated requests" to "HTTP 302 redirect to login"
6. Enable Token Store
7. Set excluded paths: `/api/health`, `/api/features/*`, `/api/stac/*`

- [ ] **Step 4: Test with Easy Auth**

```bash
# Browser: visit /api/interface/platform
# Should redirect to MS login → authenticate → page loads
# Check browser console: "[Auth] Token acquired from /.auth/me"
# Platform health check should work (fetch includes Bearer token)
# Status lookup (HTMX) should work (configRequest injects token)
```

- [ ] **Step 5: Test role gate (optional — requires AUTH_GATES_ENABLED=true)**

```bash
# Set env var on Azure
az functionapp config appsettings set \
  --name rmhazuregeoapi --resource-group rmhazure_rg \
  --settings AUTH_GATES_ENABLED=true

# Wait for restart, then test
# Maintenance endpoint should log identity with roles
```

---

## Summary

| Task | What | Changes | Tests |
|------|------|---------|-------|
| 1 | JS fetch wrapper with auth token | `base.py` COMMON_JS | Manual browser test |
| 2 | HTMX configRequest auth hook | `base.py` HTMX_JS | Manual browser test |
| 3a | AuthConfig with toggle | `config/*` (4 files) | Existing config tests |
| 3b | RBAC module | `infrastructure/auth/rbac.py` | 6 unit tests |
| 4 | Proof-of-concept audit | `triggers/admin/db_maintenance.py` | Manual curl test |
| 5 | Integration verification | None | Azure E2E |

**Auth is off by default.** The app works identically to today until Easy Auth is enabled on Azure and `AUTH_GATES_ENABLED=true` is set.
