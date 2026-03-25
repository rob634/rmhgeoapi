# Easy Auth B2B Authentication + Client Identity Capture

**Created**: 19 MAR 2026
**Status**: DESIGN
**Target**: v0.10.5+ (independent of handler decomposition — can ship anytime)
**Scope**: Gateway Function App (`rmhazuregeoapi`) — `/api/platform/*` endpoints (API + browser interface)

---

## Problem

The gateway exposes 20 `/api/platform/*` endpoints at `AuthLevel.ANONYMOUS`. Any HTTP client can submit workflows, unpublish data, approve releases, and query the catalog. There is no authentication, no caller identification, and no ownership trail. As B2B clients beyond DDH onboard, we need to:

1. **Authenticate** — reject unauthorized callers before function code runs
2. **Identify** — capture which B2B client app made each request
3. **Own** — associate submitted workflows and releases with the client that created them

## Constraints

- **Zero auth code in Python** — Azure Easy Auth validates tokens (machines) and manages sessions (browsers) at the platform level
- **Two auth flows, one config** — machines send Bearer tokens (client credentials), browser users get redirected to MS login (standard corporate SSO). Same Easy Auth instance handles both.
- **Binary access model** — "small castle with a drawbridge." If you cross the moat, you're in. No per-endpoint authorization, no role hierarchy
- **Single tenant** — all B2B clients are in the same Azure AD tenant
- **Ownership is organizational, not a security boundary** — all authenticated clients can see everything. Ownership answers "who submitted this?" not "who can access this?"
- **Single-digit B2B clients** — DDH is the primary consumer; expect 3-5 total clients long-term
- **Design for corporate deployment** — target environment has Entra ID P1 with security groups. Dev/test environment (personal Azure subscription) lacks these features

## Non-Goals

- Per-endpoint authorization or role-based access within `/platform/*`
- Rate limiting per client
- Token validation in Python code
- Client secret management (Azure AD handles this)
- Ownership-based access control (data is OUO/public — all clients see everything)

---

## Design

### 1. Auth Boundary: Azure Easy Auth (Client Credentials Flow)

Easy Auth is Azure App Service middleware that intercepts HTTP requests before they reach function code. For B2B (machine-to-machine) auth, it validates OAuth2 tokens obtained via the client credentials grant.

#### How It Works (Zero Custom Code)

```
B2B Client (e.g., DDH)
    │
    │  POST https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token
    │       grant_type=client_credentials
    │       client_id={client_app_id}
    │       client_secret={client_secret}
    │       scope=api://8c0d412b-f7b1-4920-8a5f-22f8ae9903e9/.default
    │
    ▼
Azure AD Token Endpoint
    │
    │  ← 200 OK {access_token: "eyJ0eX..."}
    │
    ▼
B2B Client
    │
    │  POST https://rmhazuregeoapi-.../api/platform/submit
    │       Authorization: Bearer eyJ0eX...
    │
    ▼
┌────────────────────────────────────────────────┐
│  Easy Auth Middleware (Azure App Service)       │
│                                                │
│  1. Extract Bearer token from Authorization    │
│  2. Validate JWT signature (Azure AD keys)     │
│  3. Check audience = api://8c0d412b-...        │
│  4. Check issuer = tenant                      │
│  5. Check app role = Platform.Access           │
│  6. INJECT identity headers:                   │
│     X-MS-CLIENT-PRINCIPAL-NAME = {display_name} │
│     X-MS-CLIENT-PRINCIPAL-ID = {object_id}     │
│     X-MS-CLIENT-PRINCIPAL-IDP = aad            │
│     X-MS-CLIENT-PRINCIPAL = {base64 JSON blob}  │
│     X-MS-TOKEN-AAD-ACCESS-TOKEN = eyJ0eX...    │
│  7. Forward request to function code           │
│                                                │
│  If invalid/missing token → 401 (never reaches │
│  function code)                                │
└────────────────────────────────────────────────┘
    │
    ▼
Function App Code (receives authenticated request with identity headers)
```

#### Dual Auth Flow: Machines + Browsers

The gateway serves two types of callers through the same Easy Auth configuration:

```
                    ┌──────────────────────────────────────┐
                    │          Incoming Request              │
                    └──────────────┬───────────────────────┘
                                   │
                    ┌──────────────▼───────────────────────┐
                    │  Has Authorization: Bearer header?    │
                    └──┬───────────────────────────────┬───┘
                       │ YES                           │ NO
                       ▼                               ▼
              ┌────────────────┐          ┌───────────────────────┐
              │ Validate JWT   │          │ Has session cookie?    │
              │ (Azure AD)     │          │ (.AppServiceAuthSession)│
              └───┬────────┬───┘          └──┬─────────────────┬──┘
                  │ valid  │ invalid         │ YES             │ NO
                  ▼        ▼                 ▼                 ▼
              ┌──────┐  ┌──────┐      ┌──────────┐    ┌──────────────┐
              │ 200  │  │ 401  │      │ 200      │    │ 302 Redirect │
              │ pass │  │ deny │      │ pass     │    │ → MS Login   │
              └──────┘  └──────┘      └──────────┘    └──────────────┘
                 ↑                        ↑                   ↑
           DDH server               Browser user         Browser user
           (machine)               (returning)           (first visit)
```

**How this works for each caller type**:

| Caller | Auth method | What happens |
|--------|------------|--------------|
| **DDH server** (machine) | `Authorization: Bearer {token}` | Token validated → 200. Redirect never fires. |
| **Browser user** (first visit) | No cookie, no token | Redirected to MS login → authenticates → redirected back with session cookie |
| **Browser user** (returning) | Session cookie | Cookie validated → 200. No redirect. |
| **Unauthenticated curl** | Nothing | Gets 302 to MS login (harmless — machines should send tokens) |

**Identity headers are the same regardless of auth method**:

| Auth method | `X-MS-CLIENT-PRINCIPAL-NAME` | `X-MS-CLIENT-PRINCIPAL-ID` |
|-------------|------------------------------|---------------------------|
| Bearer token (machine) | Service principal display name | Service principal object ID |
| Session cookie (browser) | `user@org.onmicrosoft.com` | User object ID |

The `get_caller_identity()` function captures both — for browser users it records the human's email, for machines it records the app identity. Same column, same phonebook, same ownership trail.

#### Easy Auth Configuration

```json
{
  "properties": {
    "platform": {
      "enabled": true
    },
    "globalValidation": {
      "requireAuthentication": true,
      "unauthenticatedClientAction": "RedirectToLoginPage",
      "redirectToProvider": "azureactivedirectory",
      "excludedPaths": [
        "/api/health",
        "/api/platform/health",
        "/api/features/*",
        "/api/stac/*",
        "/api/dag/*",
        "/api/dbadmin/*",
        "/api/jobs/*",
        "/api/test/*"
      ]
    },
    "identityProviders": {
      "azureActiveDirectory": {
        "enabled": true,
        "registration": {
          "openIdIssuer": "https://sts.windows.net/{TENANT_ID}/v2.0",
          "clientId": "8c0d412b-f7b1-4920-8a5f-22f8ae9903e9"
        },
        "validation": {
          "allowedAudiences": [
            "api://8c0d412b-f7b1-4920-8a5f-22f8ae9903e9"
          ]
        }
      }
    },
    "login": {
      "tokenStore": {
        "enabled": true
      }
    }
  }
}
```

Key differences from the archived Easy Auth guide (NOV 2025):
- `unauthenticatedClientAction: RedirectToLoginPage` — supports both browser users (redirect to MS login) and machine clients (Bearer token validated before redirect fires). See "Dual Auth Flow" section.
- `excludedPaths` — health, platform/health, OGC Features, STAC, admin, DAG, and test endpoints stay anonymous
- No implicit grant flow needed — client credentials uses direct token exchange
- Uses `/v2.0` issuer URL (required for client credentials with `scope=api://.../.default`). **Verify**: the existing app registration `rmhazuregeoapi-easyauth` must have `accessTokenAcceptedVersion: 2` in its manifest (check via App registrations → Manifest tab). If it's `null` or `1`, update it to `2`.

#### What Easy Auth Protects

| Path Pattern | Auth Required | Why |
|-------------|---------------|-----|
| `/api/platform/*` | Yes | B2B integration — the drawbridge |
| `/api/platform/health` | No | B2B clients need pre-auth health check |
| `/api/health` | No | Health checks, monitoring, load balancers |
| `/api/features/*` | No | Public OGC Features API |
| `/api/stac/*` | No | Public STAC catalog |
| `/api/dag/*` | No | Internal DAG status (admin use) |
| `/api/dbadmin/*` | No | Internal admin (network-restricted in prod) |
| `/api/jobs/*` | No | Legacy job endpoints (internal) |
| `/api/test/*` | No | Test/diagnostic endpoints |

### 2. App Role: Platform.Access

A single app role on the gateway's app registration. Binary: you have it or you don't.

#### App Role Definition (on rmhazuregeoapi-easyauth app registration)

```json
{
  "appRoles": [
    {
      "allowedMemberTypes": ["Application"],
      "displayName": "Platform Access",
      "description": "Full access to /api/platform/* endpoints (B2B integration)",
      "id": "<generate-guid>",
      "isEnabled": true,
      "value": "Platform.Access"
    }
  ]
}
```

`allowedMemberTypes: ["Application"]` — this role is for service principals (apps), not users. Users access via browser/Easy Auth interactive flow if needed in the future.

#### Corporate Deployment Model (Target)

In the corporate Azure AD tenant with Entra ID P1:

```
Security Group: "GeoAPI-B2B-Clients"
    ├── DDH Production (service principal)
    ├── DDH Staging (service principal)
    └── Future Client X (service principal)

Enterprise Application: rmhazuregeoapi-easyauth
    └── Assignment required: Yes
    └── Assigned: "GeoAPI-B2B-Clients" group → Role: Platform.Access

Result: Only service principals in the security group can obtain tokens.
        Adding a new client = add their SP to the group. Done.
```

#### Dev/Test Model (Personal Azure Subscription)

No security groups available (Entra ID Free). Instead:

```
Enterprise Application: rmhazuregeoapi-easyauth
    └── Assignment required: Yes
    └── Directly assigned:
        ├── DDH-Simulator (test app registration) → Role: Platform.Access
        └── Robert's user account → Role: Platform.Access (for browser testing)

Result: Same auth flow, same token validation, same identity headers.
        Only difference: direct assignment instead of group-based.
```

The auth mechanics (token validation, header injection, identity capture) are identical regardless of whether access is granted via security group or direct assignment.

### 3. Client Registry: app.platform_clients (Lazy Phonebook)

A lookup table that maps Azure AD app IDs to friendly names. **Not a security gate** — rows are created automatically on first authenticated request. Exists purely for human-readable ownership.

#### Schema

```sql
CREATE TABLE app.platform_clients (
    client_id       TEXT PRIMARY KEY,        -- Azure AD application ID (from X-MS-CLIENT-PRINCIPAL-NAME)
    display_name    TEXT NOT NULL,            -- Friendly name; defaults to client_id, update manually
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes           TEXT                     -- Free-form: "DDH production instance", contact info, etc.
);
```

#### Lazy Registration

On every mutating `/platform/*` request (submit, unpublish, approve, reject, resubmit, revoke):

```python
client_app_id = req.headers.get("X-MS-CLIENT-PRINCIPAL-NAME")
if client_app_id:
    # Upsert: create if new, update last_seen if existing
    INSERT INTO app.platform_clients (client_id, display_name, first_seen_at, last_seen_at)
    VALUES (%s, %s, NOW(), NOW())
    ON CONFLICT (client_id) DO UPDATE SET last_seen_at = NOW()
```

`display_name` defaults to `client_id` (the GUID). Update it manually whenever you onboard a client:

```sql
UPDATE app.platform_clients
SET display_name = 'DDH Production', notes = 'Data Discovery Hub - primary consumer'
WHERE client_id = '8c0d412b-f7b1-4920-8a5f-22f8ae9903e9';
```

No admin endpoint needed for single-digit clients. SQL is fine.

### 4. Ownership Columns on Existing Tables

Two new nullable columns:

```sql
ALTER TABLE app.workflow_runs ADD COLUMN submitted_by_app TEXT;
ALTER TABLE app.asset_releases ADD COLUMN submitted_by_app TEXT;
```

- **No foreign key** to `platform_clients` — the lazy upsert happens in the same request, but we don't want a FK failure to block a submission. The relationship is logical, not enforced.
- **Nullable** — existing rows and locally-submitted jobs (no Easy Auth in dev) will have NULL, which correctly means "no B2B client identity available."
- **Additive change** — safe for `action=ensure`, no rebuild required.
- **Index**: `CREATE INDEX idx_workflow_runs_submitted_by ON app.workflow_runs(submitted_by_app) WHERE submitted_by_app IS NOT NULL` (and same for `asset_releases`). Enables "show all workflows from client X" queries.

**Implementation note**: The `ALTER TABLE` statements above are illustrative. Implementation should add `submitted_by_app` as a field on the `WorkflowRun` and `AssetRelease` Pydantic models with `__sql_indexes` hints. The DDL generator handles column creation via `action=ensure`. Similarly, `platform_clients` should be a Pydantic model class following the existing pattern (`__sql_table_name`, `__sql_schema`, etc.).

#### Where Identity Gets Written

| Endpoint | Entity | Column |
|----------|--------|--------|
| `POST /platform/submit` | `workflow_runs` | `submitted_by_app` |
| `POST /platform/submit` | `asset_releases` | `submitted_by_app` (on the release record) |
| `POST /platform/unpublish` | `workflow_runs` | `submitted_by_app` (unpublish workflow) |
| `POST /platform/approve` | `asset_releases` | Could add `approved_by_app` later — not in scope |
| `POST /platform/reject` | `asset_releases` | Same — identity capture for `platform_clients` upsert |
| `POST /platform/revoke` | `asset_releases` | Same — identity capture for `platform_clients` upsert |
| `POST /platform/resubmit` | `workflow_runs` | `submitted_by_app` (new workflow run) |

All 6 mutating endpoints fire the `platform_clients` lazy upsert. The `submitted_by_app` column is only written on submit/unpublish/resubmit (workflow creation). Approve/reject/revoke identity capture is deferred (would need `approved_by_app` / `rejected_by_app` columns — out of scope).

Read-only endpoints (status, catalog, approvals list) do not write identity. App Insights logs all requests with headers if audit of reads is ever needed.

### 5. Identity Extraction Utility

A single function, used by the platform blueprint handlers:

```python
# infrastructure/platform_auth.py (or similar)
import base64
import json

def get_caller_identity(req: func.HttpRequest) -> Optional[str]:
    """
    Extract B2B caller identity from Easy Auth headers.

    Returns the Azure AD application (client) ID of the calling app,
    or None if no Easy Auth identity is present (e.g., local dev,
    anonymous access, excluded paths).

    IMPORTANT: For client credentials flow, X-MS-CLIENT-PRINCIPAL-NAME
    may contain the service principal display name (not the app ID GUID).
    We prefer the appid claim from the X-MS-CLIENT-PRINCIPAL base64 blob,
    falling back to X-MS-CLIENT-PRINCIPAL-NAME if parsing fails.
    """
    # Strategy 1: Parse the base64 principal blob for the appid claim
    principal_blob = req.headers.get("X-MS-CLIENT-PRINCIPAL")
    if principal_blob:
        try:
            decoded = json.loads(base64.b64decode(principal_blob))
            claims = {c["typ"]: c["val"] for c in decoded.get("claims", [])}
            app_id = claims.get("appid") or claims.get("azp")
            if app_id:
                return app_id
        except (json.JSONDecodeError, KeyError, ValueError):
            pass  # Fall through to simpler header

    # Strategy 2: Fall back to the name header (may be display name or app ID)
    return req.headers.get("X-MS-CLIENT-PRINCIPAL-NAME")
```

**NOTE**: The exact content of `X-MS-CLIENT-PRINCIPAL-NAME` for client credentials flow must be verified during testing (see Open Questions #2). The dual-strategy approach handles either outcome. Once verified, the function can be simplified to whichever strategy works.

That's the entire auth-related code in the Python codebase. Everything else is Azure platform configuration.

---

## Testing Strategy

### Dev Environment (Personal Azure Subscription)

**What we CAN test** (same mechanics as corporate):
- Easy Auth token validation (valid token → 200, invalid/missing → 401)
- Client credentials flow (simulate B2B client with a second app registration)
- Identity header injection and capture
- `platform_clients` lazy registration
- `submitted_by_app` column population
- `excludedPaths` (health/STAC/features still work without auth)

**What we CANNOT test** (requires Entra ID P1):
- Security group-based assignment
- Conditional access policies
- Dynamic group membership

**Test setup**:
1. Re-enable Easy Auth on `rmhazuregeoapi` with `RedirectToLoginPage` config
2. Create test app registration: `geoapi-test-client`
3. Grant `Platform.Access` role via direct assignment
4. Create a client secret for `geoapi-test-client`
5. Use `az rest` or `curl` to obtain token and call `/api/platform/submit`
6. Verify: identity headers present, `platform_clients` row created, `submitted_by_app` populated

**Test script outline**:

```bash
# 1. Get token as the test B2B client
TOKEN=$(curl -s -X POST \
  "https://login.microsoftonline.com/086aef7e-db12-4161-8a9f-777deb499cfa/oauth2/v2.0/token" \
  -d "grant_type=client_credentials" \
  -d "client_id={TEST_CLIENT_ID}" \
  -d "client_secret={TEST_CLIENT_SECRET}" \
  -d "scope=api://8c0d412b-f7b1-4920-8a5f-22f8ae9903e9/.default" \
  | jq -r '.access_token')

# 2. Call platform endpoint with token
curl -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  https://rmhazuregeoapi-.../api/platform/health

# 3. Verify anonymous access blocked
curl https://rmhazuregeoapi-.../api/platform/health
# Expected: 401 Unauthorized

# 4. Verify excluded paths still work
curl https://rmhazuregeoapi-.../api/health
# Expected: 200 OK (no auth needed)
```

### What Transfers to Corporate

The entire auth design transfers 1:1. The only corporate-specific addition:
- Replace direct service principal assignment with security group assignment
- Group membership managed by AD admins, not app developers
- Same tokens, same headers, same code, same `platform_clients` table

---

## Azure AD Setup Steps (Dev Environment)

### Prerequisites

- Existing app registration: `rmhazuregeoapi-easyauth` (client ID: `8c0d412b-f7b1-4920-8a5f-22f8ae9903e9`)
- Tenant: `086aef7e-db12-4161-8a9f-777deb499cfa`
- Easy Auth currently disabled on `rmhazuregeoapi`

### Step 1: Add App Role to Gateway App Registration

```bash
# Add Platform.Access app role
az ad app update \
  --id 8c0d412b-f7b1-4920-8a5f-22f8ae9903e9 \
  --app-roles '[{
    "allowedMemberTypes": ["Application"],
    "displayName": "Platform Access",
    "description": "Full access to /api/platform/* endpoints",
    "id": "<generate-uuid>",
    "isEnabled": true,
    "value": "Platform.Access"
  }]'
```

### Step 2: Create Test B2B Client App Registration

```bash
az ad app create \
  --display-name "geoapi-test-client" \
  --sign-in-audience AzureADMyOrg
```

### Step 3: Create Client Secret for Test Client

```bash
az ad app credential reset \
  --id {TEST_CLIENT_APP_ID} \
  --display-name "test-secret" \
  --years 1
```

### Step 4: Grant App Role to Test Client

This requires assigning the `Platform.Access` role to the test client's service principal via the Enterprise Application in Azure Portal (or Graph API).

### Step 5: Enable Easy Auth with RedirectToLoginPage

```bash
SUBSCRIPTION_ID=$(az account show --query id -o tsv)

az rest \
  --method PUT \
  --uri "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/rmhazure_rg/providers/Microsoft.Web/sites/rmhazuregeoapi/config/authsettingsV2?api-version=2022-03-01" \
  --headers "Content-Type=application/json" \
  --body '{
    "properties": {
      "platform": { "enabled": true },
      "globalValidation": {
        "requireAuthentication": true,
        "unauthenticatedClientAction": "RedirectToLoginPage",
      "redirectToProvider": "azureactivedirectory",
        "excludedPaths": [
          "/api/health",
          "/api/features/*",
          "/api/stac/*",
          "/api/dag/*",
          "/api/dbadmin/*",
          "/api/jobs/*",
          "/api/test/*"
        ]
      },
      "identityProviders": {
        "azureActiveDirectory": {
          "enabled": true,
          "registration": {
            "openIdIssuer": "https://sts.windows.net/086aef7e-db12-4161-8a9f-777deb499cfa/v2.0",
            "clientId": "8c0d412b-f7b1-4920-8a5f-22f8ae9903e9"
          },
          "validation": {
            "allowedAudiences": [
              "api://8c0d412b-f7b1-4920-8a5f-22f8ae9903e9"
            ]
          }
        }
      },
      "login": {
        "tokenStore": { "enabled": true }
      }
    }
  }'
```

### Step 6: Test

Run the test script from the Testing Strategy section above.

### Rollback

**WARNING**: The authsettingsV2 endpoint uses PUT (full replacement), not PATCH. A minimal PUT will wipe other config sections. Use the full config body with only `enabled` changed:

```bash
# Disable Easy Auth (preserves full config for re-enable)
az rest \
  --method PUT \
  --uri "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/rmhazure_rg/providers/Microsoft.Web/sites/rmhazuregeoapi/config/authsettingsV2?api-version=2022-03-01" \
  --headers "Content-Type=application/json" \
  --body '{
    "properties": {
      "platform": { "enabled": false },
      "globalValidation": {
        "requireAuthentication": true,
        "unauthenticatedClientAction": "RedirectToLoginPage",
      "redirectToProvider": "azureactivedirectory",
        "excludedPaths": [
          "/api/health", "/api/platform/health",
          "/api/features/*", "/api/stac/*", "/api/dag/*",
          "/api/dbadmin/*", "/api/jobs/*", "/api/test/*"
        ]
      },
      "identityProviders": {
        "azureActiveDirectory": {
          "enabled": true,
          "registration": {
            "openIdIssuer": "https://sts.windows.net/086aef7e-db12-4161-8a9f-777deb499cfa/v2.0",
            "clientId": "8c0d412b-f7b1-4920-8a5f-22f8ae9903e9"
          },
          "validation": {
            "allowedAudiences": ["api://8c0d412b-f7b1-4920-8a5f-22f8ae9903e9"]
          }
        }
      },
      "login": { "tokenStore": { "enabled": true } }
    }
  }'
```

To re-enable: change `"enabled": false` back to `"enabled": true` in the `platform` section.

---

## Migration Path

This feature is **fully additive** — no breaking changes, no rebuild required.

| Step | What | Breaking? |
|------|------|-----------|
| 1 | Add `platform_clients` table to schema model | No — `action=ensure` creates it |
| 2 | Add `submitted_by_app` columns to `workflow_runs` and `asset_releases` | No — nullable, additive |
| 3 | Add `get_caller_identity()` utility | No — new file |
| 4 | Wire identity capture into submit/unpublish/resubmit handlers | No — reads optional header, writes optional column |
| 5 | Enable Easy Auth on Azure (portal/CLI) | No — platform config, not code |
| 6 | Create test client + verify | No — testing only |

Steps 1-4 can deploy before Easy Auth is enabled. Without Easy Auth, `X-MS-CLIENT-PRINCIPAL-NAME` will be absent, `submitted_by_app` will be NULL, and everything works exactly as today. Easy Auth is a light switch you flip independently.

---

## Epoch 4 Freeze Compliance

This work is **outside the freeze scope**. The freeze applies to CoreMachine, Python job classes, and Service Bus. This feature:
- Adds a new table (additive schema)
- Adds nullable columns (additive schema)
- Reads HTTP headers in the gateway layer (platform integration, not orchestration)
- Azure platform configuration (not code)

No CoreMachine changes. No SB changes. No job class changes.

---

## Azure Portal Clickthrough Guide (eService Request Reference)

In the corporate environment, these steps will be filed as eService requests to IT/Security. This section provides exact portal paths and screenshots-equivalent descriptions so the request can be precise.

### Request 1: Create App Registration for the Gateway API

**Portal Path**:
```
Azure Portal (portal.azure.com)
→ Microsoft Entra ID (left sidebar)
→ App registrations
→ + New registration
```

**Form Fields**:
| Field | Value | Notes |
|-------|-------|-------|
| Name | `geoapi-gateway` (or org naming convention) | This is the API that B2B clients call |
| Supported account types | "Accounts in this organizational directory only (Single tenant)" | Single tenant — all clients are internal |
| Redirect URI | Leave blank | Not needed for client credentials flow |

**Click**: Register

**After creation, note these values**:
- **Application (client) ID** — this becomes the `clientId` in Easy Auth config and the `scope` audience
- **Directory (tenant) ID** — used in token endpoint URL

**Then set the Application ID URI**:
```
App registration → geoapi-gateway
→ Manage → Expose an API (left sidebar)
→ Set (next to "Application ID URI")
→ Accept default: api://{application-id}
→ Save
```

This URI becomes the `scope` that B2B clients request tokens for: `api://{application-id}/.default`

---

### Request 2: Add App Role (Platform.Access)

**Portal Path**:
```
App registration → geoapi-gateway
→ Manage → App roles (left sidebar)
→ + Create app role
```

**Form Fields**:
| Field | Value | Notes |
|-------|-------|-------|
| Display name | `Platform Access` | Human-readable |
| Allowed member types | **Applications** | This role is for service principals (apps), not users |
| Value | `Platform.Access` | The claim value that appears in the token |
| Description | `Full access to /api/platform/* endpoints (B2B integration)` | |
| Enable this app role | Checked | |

**Click**: Apply

**Result**: The `Platform.Access` role now appears in the app's manifest. B2B client service principals can be assigned this role.

---

### Request 3: Create App Registration for Each B2B Client

Repeat for each B2B client (e.g., DDH, future clients).

**Portal Path**:
```
Azure Portal
→ Microsoft Entra ID
→ App registrations
→ + New registration
```

**Form Fields**:
| Field | Value | Notes |
|-------|-------|-------|
| Name | `ddh-geoapi-client` (or org naming convention) | Identifies the calling application |
| Supported account types | "Accounts in this organizational directory only" | Same tenant |
| Redirect URI | Leave blank | Client credentials flow — no redirect |

**Click**: Register

**Then create a client secret** (or certificate):
```
App registration → ddh-geoapi-client
→ Manage → Certificates & secrets (left sidebar)
→ Client secrets tab
→ + New client secret
```

| Field | Value |
|-------|-------|
| Description | `geoapi-b2b-access` |
| Expires | 24 months (or per org policy) |

**Click**: Add

**IMPORTANT**: Copy the secret **Value** immediately — it is only shown once. The **Secret ID** is NOT the secret value.

**Give to the DDH team**: Application (client) ID + Secret Value + Tenant ID + Scope (`api://{gateway-app-id}/.default`). They use these to obtain tokens.

**Token guidance for B2B clients**: Azure AD client credentials tokens have a default lifetime of 60-90 minutes. Clients should cache tokens and only refresh when expired (standard OAuth2 practice). Most HTTP client libraries (MSAL, azure-identity) handle this automatically.

---

### Request 4: Grant App Role to B2B Client (Direct Assignment)

This step authorizes the B2B client's service principal to call the gateway.

**Portal Path**:
```
Azure Portal
→ Microsoft Entra ID
→ Enterprise applications (left sidebar, under "Manage")
→ Search: "geoapi-gateway"
→ Click on it
```

**Important distinction**: "App registrations" and "Enterprise applications" are different views of the same object. Enterprise applications show the **service principal** (the identity), not the registration (the config). Role assignment happens here.

```
Enterprise application → geoapi-gateway
→ Manage → Users and groups (left sidebar)
→ + Add user/group
```

**Assignment Form**:
1. **Users and groups** → Click "None Selected"
   - Switch to the **"Service principals"** tab (not "Users" tab!)
   - Search for: `ddh-geoapi-client`
   - Select it → Click "Select"

2. **Select a role** → Click "None Selected"
   - Choose: `Platform Access`
   - Click "Select"

3. **Click**: Assign

**Result**: The DDH client's service principal now has the `Platform.Access` role. When it requests a token with `scope=api://{gateway-app-id}/.default`, the token will include the role claim, and Easy Auth will allow the request.

---

### Request 5: Create Security Group (Corporate — Entra ID P1)

**Portal Path**:
```
Azure Portal
→ Microsoft Entra ID
→ Groups (left sidebar)
→ + New group
```

**Form Fields**:
| Field | Value |
|-------|-------|
| Group type | Security |
| Group name | `GeoAPI-B2B-Clients` |
| Group description | `Service principals authorized to call /api/platform/* endpoints on the Geospatial API` |
| Membership type | Assigned |

**Click**: Create

**Then add members**:
```
Groups → GeoAPI-B2B-Clients
→ Members (left sidebar)
→ + Add members
→ Search for each B2B client service principal (e.g., "ddh-geoapi-client")
→ Select → Add
```

**Then assign the group to the gateway** (replaces Request 4 per-client assignment):
```
Enterprise applications → geoapi-gateway
→ Users and groups
→ + Add user/group
→ Select: "GeoAPI-B2B-Clients" group
→ Role: "Platform Access"
→ Assign
```

**Also enable assignment requirement**:
```
Enterprise applications → geoapi-gateway
→ Properties (left sidebar)
→ Assignment required? → Yes
→ Save
```

**Result**: Only service principals in the `GeoAPI-B2B-Clients` security group can obtain valid tokens. Adding a new B2B client = add their SP to the group. Removing = remove from group. No app registration changes needed.

---

### Request 6: Enable Easy Auth on the Function App

**Portal Path**:
```
Azure Portal
→ Resource Groups → rmhazure_rg (or corporate RG)
→ Function App (the gateway app)
→ Settings → Authentication (left sidebar)
→ Add identity provider
```

**Provider Configuration**:
| Field | Value | Notes |
|-------|-------|-------|
| Identity provider | Microsoft | |
| Tenant type | Workforce | Azure AD / Entra ID |
| App registration | Use existing: `geoapi-gateway` | The app reg from Request 1 |
| Supported account types | Current tenant - Single tenant | |
| Restrict access | Require authentication | |
| Unauthenticated requests | **HTTP 302 Redirect to login page** | Supports both browser SSO and machine-to-machine auth |
| Token store | Enabled | |

**Click**: Add

**Then configure excluded paths** (requires v2 API or ARM template — not available in portal UI as of MAR 2026):

The portal UI does not expose `excludedPaths`. This must be configured via:

**Option A — Azure CLI** (if IT allows):
```bash
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
az rest --method PUT \
  --uri "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/{RG}/providers/Microsoft.Web/sites/{APP_NAME}/config/authsettingsV2?api-version=2022-03-01" \
  --headers "Content-Type=application/json" \
  --body '{
    "properties": {
      "globalValidation": {
        "excludedPaths": [
          "/api/health",
          "/api/features/*",
          "/api/stac/*",
          "/api/dag/*",
          "/api/dbadmin/*",
          "/api/jobs/*",
          "/api/test/*"
        ]
      }
    }
  }'
```

**Option B — ARM Template / Bicep** (if org uses IaC):
Include `excludedPaths` in the `authsettingsV2` resource definition.

**Option C — Azure Resource Explorer** (portal.azure.com → Resource Explorer):
```
subscriptions/{id}/resourceGroups/{rg}/providers/Microsoft.Web/sites/{app}/config/authsettingsV2
→ Edit → Add excludedPaths to globalValidation → PUT
```

**Include in eService request**: "We need the following paths excluded from authentication on the Function App: `/api/health`, `/api/platform/health`, `/api/features/*`, `/api/stac/*`, `/api/dag/*`, `/api/dbadmin/*`, `/api/jobs/*`, `/api/test/*`. These are public endpoints that must remain accessible without authentication. This requires the `excludedPaths` property in the authsettingsV2 configuration."

---

### eService Request Template

Use this template when filing with IT/Security:

```
Subject: Enable Azure AD Authentication on Function App [APP_NAME]

Request Type: Azure AD / Entra ID Configuration

Summary:
Enable App Service Authentication (Easy Auth) on Function App [APP_NAME]
to require Azure AD authentication for B2B API endpoints (/api/platform/*).
Other endpoints must remain publicly accessible.

Detailed Steps Required:

1. APP REGISTRATION (API):
   - Create app registration: [NAME]
   - Single tenant, no redirect URI
   - Set Application ID URI: api://[auto-generated-id]
   - Add app role: "Platform.Access" (Application type, value: "Platform.Access")

2. APP REGISTRATION (B2B CLIENT):
   - Create app registration: [CLIENT_NAME]
   - Single tenant, no redirect URI
   - Create client secret (24-month expiry)
   - Provide credentials to [CLIENT_TEAM_CONTACT]

3. SECURITY GROUP:
   - Create security group: "GeoAPI-B2B-Clients"
   - Add [CLIENT_NAME] service principal as member

4. ROLE ASSIGNMENT:
   - Enterprise app [API_NAME]: Assignment required = Yes
   - Assign "GeoAPI-B2B-Clients" group → Role: "Platform.Access"

5. EASY AUTH:
   - Enable App Service Authentication on [APP_NAME]
   - Provider: Microsoft (Azure AD)
   - Unauthenticated action: Redirect to login page (supports browser SSO + machine auth)
   - Excluded paths: /api/health, /api/platform/health, /api/features/*,
     /api/stac/*, /api/dag/*, /api/dbadmin/*, /api/jobs/*, /api/test/*
   - Token store: Enabled

Expected Outcome:
- Requests to /api/platform/* without valid Bearer token → 401
- Requests to /api/platform/* with valid token from authorized app → 200
- Requests to /api/health, /api/features/*, etc. → 200 (no auth)

Testing Contact: [YOUR_NAME]
```

---

## App-to-App Auth Test Playbook (Dev Environment)

Step-by-step instructions to test the full client credentials flow in the personal Azure tenant. Resume here when ready to experiment.

### Current State (25 MAR 2026)

| Resource | Status | ID |
|----------|--------|-----|
| Gateway app registration | Exists, no roles defined | `8c0d412b-f7b1-4920-8a5f-22f8ae9903e9` (`rmhazuregeoapi-easyauth`) |
| Application ID URI | Set | `api://8c0d412b-f7b1-4920-8a5f-22f8ae9903e9` |
| Easy Auth on Function App | Configured but **disabled** (`platform.enabled: false`) | — |
| Tenant ID | `086aef7e-db12-4161-8a9f-777deb499cfa` | `rob634gmail.onmicrosoft.com` |
| Test client app | Candidate: `geoapi` (cf24d053) from Nov 2024, or create fresh | — |
| Platform.Access role | **Not defined yet** | — |
| Token version | **Needs checking** (must be v2) | — |
| Other app registrations | `rmhgeoapispn` (Aug 2025), `rmhazure_sp` (Dec 2024), `B2C-geotiler` (Mar 2026 — Service Layer) | — |

### Step 0: Pre-flight checks

```bash
# Check token version on gateway app registration (must be 2, not null or 1)
az ad app show --id 8c0d412b-f7b1-4920-8a5f-22f8ae9903e9 \
  --query "api.requestedAccessTokenVersion"

# If null or 1, update to 2:
az ad app update --id 8c0d412b-f7b1-4920-8a5f-22f8ae9903e9 \
  --set api.requestedAccessTokenVersion=2
```

### Step 1: Add Platform.Access role to gateway app registration

```bash
# Generate a UUID for the role ID
ROLE_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
echo "Role ID: $ROLE_ID"

# Add the app role
az ad app update \
  --id 8c0d412b-f7b1-4920-8a5f-22f8ae9903e9 \
  --app-roles "[{
    \"allowedMemberTypes\": [\"Application\"],
    \"displayName\": \"Platform Access\",
    \"description\": \"Full access to /api/platform/* endpoints (B2B integration)\",
    \"id\": \"$ROLE_ID\",
    \"isEnabled\": true,
    \"value\": \"Platform.Access\"
  }]"

# Verify
az ad app show --id 8c0d412b-f7b1-4920-8a5f-22f8ae9903e9 --query "appRoles"
```

### Step 2: Create test B2B client app registration

```bash
# Create the test client (simulates DDH or another B2B caller)
az ad app create \
  --display-name "geoapi-test-client" \
  --sign-in-audience AzureADMyOrg

# Note the appId from the output — this is TEST_CLIENT_ID

# Create a client secret (the test client needs this to get tokens)
az ad app credential reset \
  --id {TEST_CLIENT_ID} \
  --display-name "test-secret" \
  --years 1

# SAVE THE PASSWORD FROM THE OUTPUT — shown only once
# This is TEST_CLIENT_SECRET
```

### Step 3: Create service principal for test client (required for role assignment)

```bash
# The service principal may already exist — this is idempotent
az ad sp create --id {TEST_CLIENT_ID}
```

### Step 4: Assign Platform.Access role to test client

This must be done via Graph API (portal or CLI):

```bash
# Get the service principal object IDs
GATEWAY_SP_ID=$(az ad sp show --id 8c0d412b-f7b1-4920-8a5f-22f8ae9903e9 --query "id" -o tsv)
CLIENT_SP_ID=$(az ad sp show --id {TEST_CLIENT_ID} --query "id" -o tsv)

# Get the role ID (from Step 1, or query it)
ROLE_ID=$(az ad app show --id 8c0d412b-f7b1-4920-8a5f-22f8ae9903e9 \
  --query "appRoles[?value=='Platform.Access'].id" -o tsv)

# Assign the role
az rest --method POST \
  --uri "https://graph.microsoft.com/v1.0/servicePrincipals/$GATEWAY_SP_ID/appRoleAssignedTo" \
  --headers "Content-Type=application/json" \
  --body "{
    \"principalId\": \"$CLIENT_SP_ID\",
    \"resourceId\": \"$GATEWAY_SP_ID\",
    \"appRoleId\": \"$ROLE_ID\"
  }"
```

### Step 5: Enable Easy Auth on Function App

```bash
SUBSCRIPTION_ID=$(az account show --query id -o tsv)

az rest \
  --method PUT \
  --uri "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/rmhazure_rg/providers/Microsoft.Web/sites/rmhazuregeoapi/config/authsettingsV2?api-version=2022-03-01" \
  --headers "Content-Type=application/json" \
  --body '{
    "properties": {
      "platform": { "enabled": true },
      "globalValidation": {
        "requireAuthentication": true,
        "unauthenticatedClientAction": "RedirectToLoginPage",
        "redirectToProvider": "azureactivedirectory",
        "excludedPaths": [
          "/api/health",
          "/api/platform/health",
          "/api/features/*",
          "/api/stac/*",
          "/api/dag/*",
          "/api/dbadmin/*",
          "/api/jobs/*",
          "/api/test/*"
        ]
      },
      "identityProviders": {
        "azureActiveDirectory": {
          "enabled": true,
          "registration": {
            "openIdIssuer": "https://sts.windows.net/086aef7e-db12-4161-8a9f-777deb499cfa/v2.0",
            "clientId": "8c0d412b-f7b1-4920-8a5f-22f8ae9903e9"
          },
          "validation": {
            "allowedAudiences": [
              "api://8c0d412b-f7b1-4920-8a5f-22f8ae9903e9"
            ]
          }
        }
      },
      "login": {
        "tokenStore": { "enabled": true }
      }
    }
  }'
```

### Step 6: Test the full flow

```bash
# --- TEST A: Get token as the test B2B client ---
TOKEN=$(curl -s -X POST \
  "https://login.microsoftonline.com/086aef7e-db12-4161-8a9f-777deb499cfa/oauth2/v2.0/token" \
  -d "grant_type=client_credentials" \
  -d "client_id={TEST_CLIENT_ID}" \
  -d "client_secret={TEST_CLIENT_SECRET}" \
  -d "scope=api://8c0d412b-f7b1-4920-8a5f-22f8ae9903e9/.default" \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token','FAILED'))")

echo "Token: ${TOKEN:0:20}..."

# --- TEST B: Authenticated call to protected endpoint ---
curl -s -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/json" \
  "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/platform/health"
# Expected: 200 OK with health JSON

# --- TEST C: Unauthenticated call to protected endpoint ---
curl -s -o /dev/null -w "%{http_code}" \
  "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/platform/status"
# Expected: 302 (redirect to login) or 401

# --- TEST D: Unauthenticated call to excluded path ---
curl -s -o /dev/null -w "%{http_code}" \
  "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health"
# Expected: 200 (no auth required)

# --- TEST E: Check identity headers (if your app echoes them) ---
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/platform/health" \
  -v 2>&1 | grep -i "x-ms-client"
# Look for: X-MS-CLIENT-PRINCIPAL-NAME, X-MS-CLIENT-PRINCIPAL-ID

# --- TEST F: Decode the token to see what claims it has ---
echo $TOKEN | cut -d. -f2 | base64 -d 2>/dev/null | python3 -m json.tool
# Look for: "roles": ["Platform.Access"], "appid": "{TEST_CLIENT_ID}"
```

### Step 7: Rollback (disable Easy Auth)

If things go wrong, disable Easy Auth without losing config:

```bash
# Same PUT as Step 5 but with platform.enabled = false
az rest \
  --method PUT \
  --uri "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/rmhazure_rg/providers/Microsoft.Web/sites/rmhazuregeoapi/config/authsettingsV2?api-version=2022-03-01" \
  --headers "Content-Type=application/json" \
  --body '{
    "properties": {
      "platform": { "enabled": false },
      "globalValidation": {
        "requireAuthentication": true,
        "unauthenticatedClientAction": "RedirectToLoginPage",
        "redirectToProvider": "azureactivedirectory",
        "excludedPaths": [
          "/api/health", "/api/platform/health",
          "/api/features/*", "/api/stac/*", "/api/dag/*",
          "/api/dbadmin/*", "/api/jobs/*", "/api/test/*"
        ]
      },
      "identityProviders": {
        "azureActiveDirectory": {
          "enabled": true,
          "registration": {
            "openIdIssuer": "https://sts.windows.net/086aef7e-db12-4161-8a9f-777deb499cfa/v2.0",
            "clientId": "8c0d412b-f7b1-4920-8a5f-22f8ae9903e9"
          },
          "validation": {
            "allowedAudiences": ["api://8c0d412b-f7b1-4920-8a5f-22f8ae9903e9"]
          }
        }
      },
      "login": { "tokenStore": { "enabled": true } }
    }
  }'
```

### What to Record After Testing

| Question | How to Answer | Record Here |
|----------|--------------|-------------|
| Does `excludedPaths` support wildcards? | Test D: does `/api/test/logging` return 200? | |
| What does `X-MS-CLIENT-PRINCIPAL-NAME` contain? | Test E: is it the app display name or the app ID GUID? | |
| Does the token include `roles` claim? | Test F: decode token, look for `"roles": ["Platform.Access"]` | |
| Token version (v1 vs v2)? | Test F: decode token, check `"ver"` field | |

### Corporate Deployment Notes (25 MAR 2026)

**Entra role required to assign app roles**: Cloud Application Administrator or Application Administrator (Entra built-in roles). An Entra admin cannot selectively restrict this — if someone has the role, they can assign app roles on any enterprise application in the tenant.

**eService request flow**:
1. **You** (app registration owner) → define roles, write eService request using template in this spec
2. **Cloud Application Administrator** → assigns roles to service principals, enables Easy Auth
3. They will ask who owns the app registration — answer: you/your team
4. Use the eService Request Template section above for exact portal clicks

**Tenant authorization policy** (checked 25 MAR 2026 on personal tenant):
- `allowedToCreateApps`: true (corporate likely false — need IT to create app regs)
- `allowedToCreateSecurityGroups`: true (corporate may vary)
- `permissionGrantPoliciesAssigned`: null (corporate will have restrictive policies)

---

## Open Questions (Resolve During Testing)

1. **`excludedPaths` wildcard support** — verify that Azure Easy Auth v2 supports glob patterns like `/api/features/*`. Test: enable Easy Auth with `excludedPaths: ["/api/test/*"]` and confirm `/api/test/logging` returns 200 without auth. If wildcards don't work, list each sub-path explicitly.
2. **`X-MS-CLIENT-PRINCIPAL-NAME` content for client credentials** — for app-to-app auth, this header likely contains the service principal **display name** (not the app ID GUID). The `get_caller_identity()` function handles both cases by preferring the `appid` claim from `X-MS-CLIENT-PRINCIPAL` base64 blob, falling back to `X-MS-CLIENT-PRINCIPAL-NAME`. The test will confirm which strategy is needed, and the function can be simplified afterward. Once resolved, also decide `platform_clients.client_id` column naming (stays `client_id` if it stores the GUID, rename to `app_principal_name` if it stores display names).
3. **`accessTokenAcceptedVersion` on app registration** — verify the existing `rmhazuregeoapi-easyauth` app registration has version `2` in its manifest. If `null` or `1`, update to `2` before enabling Easy Auth with the `/v2.0` issuer URL.
4. **`approved_by_app` on releases** — not in scope but worth noting: when an approve/reject/revoke call comes from a B2B client, we could capture that identity too. Trivial to add later with the same pattern.
5. **Target app during migration** — currently `rmhazuregeoapi` (standalone mode, only running app). In the v0.11.0 end state, the gateway may be a separate app. `excludedPaths` covers all non-platform routes, so the design works for both standalone and gateway-only modes without change.
