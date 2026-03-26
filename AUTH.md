# DDHGeo Gateway — Auth Context for UI Fix

## Platform Overview

Four apps, all in the same ASE (QA environment):

| App | Resource | Purpose |
|-----|----------|---------|
| Gateway | `fngddatahubetlqa-qa` (Function App) | Entry point, hosts admin UI + API, handles client auth |
| Orchestrator | Web App (Docker) | DAG polling loop, reads/writes Postgres state |
| Worker(s) | Web App (Docker) | Atomic ETL tasks, horizontally scaled |
| TiTiler/TiPG | Web App (Docker) | Read-only raster/vector tile serving |

**Key architectural point:** Apps do NOT call each other directly. All coordination happens through shared Postgres state tables. The only real auth boundary is **client → Gateway**.

---

## App Registration

Single app registration for the entire platform:

| Field | Value |
|-------|-------|
| Name | `QA_spn_ddhgeoqa_Service` |
| Client ID | `5f89a396-2cb3-44fa-a3e9-8d997d6a6609` |
| Tenant ID | `31a2fec0-266b-4c67-b56e-2796d8f59c36` |
| Application ID URI | `api://5f89a396-2cb3-44fa-a3e9-8d997d6a6609` |

---

## Easy Auth Configuration (Gateway)

- **App Service Authentication:** Enabled
- **Restrict access:** Require authentication
- **Unauthenticated requests:** HTTP 302 redirect to Microsoft login
- **Token store:** Enabled ✅ (this is what makes `/.auth/me` work)
- **Identity provider:** Microsoft (Entra)

---

## Authorization Model

**"Require assignment" is enabled** on the app registration. This means:

- Users not assigned a role are rejected by Entra at login — they never get a token
- Users assigned `GeoAdmin` get a token with that role claim
- The application code decides what `GeoAdmin` means in terms of allowed operations

**Current role:** `GeoAdmin` = full platform access (submit jobs, view results, manage platform)

**Role claim in token** (confirmed via `/.auth/me`):
```json
{
  "typ": "roles",
  "val": "GeoAdmin"
}
```

Entra is the bouncer (verifies identity + role assignment). App code is the venue (decides what each role can do inside).

---

## The 401 Problem

### What's happening

```
Browser → GET /api/interface/submit   ✅ (serves HTML page, Easy Auth allows)
Browser → POST /api/platform/submit   ❌ 401 (naked fetch, no Authorization header)
```

The UI page loads fine. But JavaScript `fetch()` calls to `/api/platform/*` endpoints go out with no auth header. Easy Auth sees an unauthenticated request and blocks it. The Gateway has no idea the request originated from its own UI.

### The Fix

Easy Auth stores the user's token in the session (Token store = Enabled). Retrieve it from `/.auth/me` and attach it to all API calls.

**Confirmed working — `/.auth/me` returns:**
```json
{
  "id_token": "<jwt>",
  "provider_name": "aad",
  "user_id": "rharrison1@worldbankgroup.org",
  "user_claims": [...]
}
```

Note: `/.auth/me` returns `id_token`, not a separate `access_token`. Since the UI and API share the same app registration, use the `id_token` as the Bearer token.

### Implementation Pattern

```javascript
// On page load — retrieve token once, cache for session
let gatewayToken = null;

async function getToken() {
  if (gatewayToken) return gatewayToken;
  const response = await fetch('/.auth/me');
  const data = await response.json();
  gatewayToken = data[0].id_token;
  return gatewayToken;
}

// Wrap all /api/platform/* calls with auth header
async function apiCall(endpoint, method = 'GET', body = null) {
  const token = await getToken();
  const options = {
    method,
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    }
  };
  if (body) options.body = JSON.stringify(body);
  return fetch(endpoint, options);
}

// Usage
async function submitJob(payload) {
  const response = await apiCall('/api/platform/submit', 'POST', payload);
  return response.json();
}
```

### Important Notes

- Token expires ~1 hour after login. Easy Auth handles refresh automatically — if you get a 401 mid-session, re-fetch from `/.auth/me`
- `/.auth/me` only works when called from the Gateway's own domain: `https://fngddatahubetlqa-qa.ocappsaseqa2.appserviceenvironment.net`
- The user must have completed the login redirect before `/.auth/me` returns a valid token

---

## ID Token vs Access Token

| | ID Token | Access Token |
|--|----------|--------------|
| **Purpose** | Proves identity | Proves authorization for a resource |
| **Audience (`aud`)** | Client app ID | Target API (`api://...`) |
| **Used by** | UI (know who logged in) | API (validate caller has access) |
| **Contains** | Name, email, roles | Scopes, roles |

In this case both tokens share the same `aud` (`5f89a396...`) because the UI and API are the same app registration — so the `id_token` is valid for API calls.

---

## Token Claims Reference

Confirmed claims from live token:

```json
{
  "aud": "5f89a396-2cb3-44fa-a3e9-8d997d6a6609",
  "iss": "https://login.microsoftonline.com/31a2fec0-266b-4c67-b56e-2796d8f59c36/v2.0",
  "email": "rharrison1@worldbankgroup.org",
  "name": "Robert Mansour Harrison",
  "roles": ["GeoAdmin"],
  "preferred_username": "rharrison1@worldbankgroup.org",
  "tid": "31a2fec0-266b-4c67-b56e-2796d8f59c36",
  "ver": "2.0"
}
```

Backend authorization check (FastAPI example):
```python
def require_geo_admin(token_claims: dict):
    roles = token_claims.get("roles", [])
    if "GeoAdmin" not in roles:
        raise HTTPException(status_code=403, detail="GeoAdmin role required")
```

---

## URL Reference

| Environment | Base URL |
|-------------|----------|
| QA (internal ASE) | `https://fngddatahubetlqa-qa.ocappsaseqa2.appserviceenvironment.net` |
| QA (custom domain) | `https://ddhgeoqa.worldbank.org` |

The custom domain resolves to an internal IP (`10.168.206.4`) behind the WBG corporate reverse proxy. TLS is terminated at the proxy layer — the Sectigo EV cert covering all environments lives there, not in the App Service binding.

---

## Outstanding Item

The app registration currently has **1 client secret** (`Client credentials: 0 certificate, 1 secret`). This should be rotated out in favor of managed identity authentication per RITM00009453723. Not blocking the UI fix but worth noting — the secret is a rotation/expiry risk.