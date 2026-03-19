# Easy Auth Setup Guide: B2B Authentication + Browser SSO

**Created**: 19 MAR 2026
**Design Spec**: `docs/superpowers/specs/2026-03-19-easy-auth-b2b-identity-design.md`

---

## How the Pieces Connect

There are three objects in Azure that work together. Understanding how they connect is the key to the whole setup.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        MICROSOFT ENTRA ID                           │
│                                                                     │
│  ┌─────────────────────────────┐  ┌──────────────────────────────┐ │
│  │  App Registration           │  │  App Registration            │ │
│  │  "geoapi-gateway"           │  │  "ddh-client"                │ │
│  │                             │  │                              │ │
│  │  Application (client) ID:   │  │  Application (client) ID:   │ │
│  │  aaaaaaaa-bbbb-cccc-...     │  │  dddddddd-eeee-ffff-...     │ │
│  │                             │  │                              │ │
│  │  Exposes:                   │  │  Has:                        │ │
│  │  - App ID URI:              │  │  - Client secret (password)  │ │
│  │    api://aaaaaaaa-bbbb-...  │  │                              │ │
│  │  - App role:                │  │  Granted:                    │ │
│  │    "Platform.Access"        │  │  - "Platform.Access" role    │ │
│  │                             │  │    on geoapi-gateway         │ │
│  │  THE API's IDENTITY         │  │  A CLIENT's IDENTITY         │ │
│  └──────────────┬──────────────┘  └──────────────────────────────┘ │
│                 │                                                    │
│     "I am the Geospatial API.                                       │
│      Anyone who wants to call me                                    │
│      must present a token scoped                                    │
│      to my App ID URI."                                             │
│                 │                                                    │
└─────────────────┼────────────────────────────────────────────────────┘
                  │
                  │ LINKED BY: client ID
                  │
                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     FUNCTION APP (App Service)                       │
│                                                                     │
│  Settings → Authentication                                          │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  Easy Auth Configuration                                      │  │
│  │                                                               │  │
│  │  Identity provider: Microsoft (Azure AD)                      │  │
│  │  Client ID: aaaaaaaa-bbbb-cccc-...  ◄── SAME as app reg      │  │
│  │  Issuer URL: https://sts.windows.net/{tenant}/v2.0            │  │
│  │  Allowed audiences: api://aaaaaaaa-bbbb-cccc-...              │  │
│  │                                                               │  │
│  │  "When a request arrives, validate that the token             │  │
│  │   was issued for ME (my client ID / audience)                 │  │
│  │   by MY TENANT (issuer URL)."                                 │  │
│  │                                                               │  │
│  │  Unauthenticated action: Redirect to login page               │  │
│  │  Excluded paths: /api/health, /api/features/*, ...            │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  Your function code runs AFTER Easy Auth validates the request.     │
│  Identity headers (X-MS-CLIENT-PRINCIPAL-*) are injected.           │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### The Connection: App Registration → Easy Auth

The app registration and Easy Auth are linked by a single value: **the Application (client) ID**.

1. You create an app registration in Entra ID. Azure gives it an Application (client) ID — a GUID.
2. You go to the Function App → Settings → Authentication and say "use Microsoft as identity provider."
3. You paste **the same client ID** into the Easy Auth config.

Now Easy Auth knows: "I am `geoapi-gateway`. Any token must have `audience: api://aaaaaaaa-bbbb-...` (my App ID URI) and must come from my tenant."

**That's the entire connection.** Easy Auth reads the app registration's metadata (via OpenID Connect discovery) to know how to validate tokens. You don't configure certificates, signing keys, or token formats — Azure handles all of that internally because both sides (Entra ID and App Service) are Azure services that trust each other.

```
App Registration                    Easy Auth Config
─────────────────                   ────────────────
Application (client) ID   ◄═══════► Client ID
  aaaaaaaa-bbbb-cccc-...             aaaaaaaa-bbbb-cccc-...

App ID URI                 ◄═══════► Allowed Audiences
  api://aaaaaaaa-bbbb-...            api://aaaaaaaa-bbbb-...

Tenant ID                  ◄═══════► Issuer URL
  086aef7e-db12-...                  https://sts.windows.net/086aef7e-.../v2.0

App Roles                  ◄═══════► (validated automatically from token claims)
  Platform.Access                    Token must contain role claim
```

---

## Step-by-Step Setup

### Step 1: Create the API's App Registration

This is the identity of YOUR API — the thing that B2B clients and browser users authenticate against.

**Portal Path**:
```
Azure Portal (portal.azure.com)
→ Microsoft Entra ID (left sidebar)
→ App registrations (under "Manage")
→ + New registration
```

**Fill in**:

| Field | Value |
|-------|-------|
| **Name** | `geoapi-gateway` (or your org naming convention) |
| **Supported account types** | Accounts in this organizational directory only (Single tenant) |
| **Redirect URI** | Leave blank for now |

**Click**: Register

**You'll land on the Overview page. Note these two values:**

| Value | Where to find it | What it's for |
|-------|------------------|---------------|
| **Application (client) ID** | Overview page, top section | Goes into Easy Auth config |
| **Directory (tenant) ID** | Overview page, top section | Goes into issuer URL |

#### 1a: Set the Application ID URI

This creates the `api://...` URI that tokens will be scoped to.

```
Still on the app registration page:
→ Manage → Expose an API (left sidebar)
→ Click "Set" next to "Application ID URI"
→ Accept the default: api://{application-id}
→ Click Save
```

**What this does**: Creates the scope `api://aaaaaaaa-bbbb-.../.default` that B2B clients will request tokens for. Without this URI, clients can't request tokens for your API.

#### 1b: Add the Redirect URI (for browser auth)

Browser users will be redirected to MS login and then back. Easy Auth handles the callback at a fixed path.

```
Still on the app registration page:
→ Manage → Authentication (left sidebar)
→ + Add a platform → Web
→ Redirect URI: https://{your-function-app-url}/.auth/login/aad/callback
→ Check: ☑ ID tokens (used for implicit and hybrid flows)
→ Click Configure
```

Example redirect URI for dev:
```
https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/.auth/login/aad/callback
```

**What this does**: After a browser user logs in at Microsoft's login page, Azure AD needs to know where to send them back. This URI tells it "send them back to Easy Auth's callback endpoint." Easy Auth then creates a session cookie and redirects the user to the page they originally requested.

#### 1c: Verify Token Version

```
Still on the app registration page:
→ Manage → Manifest (left sidebar)
→ Find "accessTokenAcceptedVersion"
→ Should be: 2 (not null or 1)
→ If it's null or 1, change it to 2 and click Save
```

**What this does**: Ensures the app registration accepts v2.0 tokens, which is what the client credentials flow produces when using `scope=api://.../.default`.

---

### Step 2: Add the Platform.Access App Role

This defines a role that you can grant to B2B client apps. Think of it as: "I have a door called Platform.Access. I decide who gets a key."

```
Still on the geoapi-gateway app registration:
→ Manage → App roles (left sidebar)
→ + Create app role
```

**Fill in**:

| Field | Value |
|-------|-------|
| **Display name** | Platform Access |
| **Allowed member types** | **Applications** (not Users, not Both) |
| **Value** | Platform.Access |
| **Description** | Full access to /api/platform/* endpoints (B2B integration) |
| **Enable this app role** | ☑ Checked |

**Click**: Apply

**Why "Applications" not "Users"?** This role is for service principals (machine identities like DDH). Browser users are authenticated by the login flow — they don't need a role assignment. In the corporate environment, browser access is controlled by the security group on the Enterprise Application (Step 5). The app role is specifically for machine-to-machine authorization.

> **Note**: If you later want to differentiate browser user permissions (e.g., admin vs viewer), you would create additional app roles with `allowedMemberTypes: ["User"]` or `["User", "Application"]`. Not needed now.

---

### Step 3: Create a B2B Client App Registration

Each machine that calls your API needs its own identity. This is DDH's "ID card."

**Portal Path**:
```
Azure Portal
→ Microsoft Entra ID
→ App registrations
→ + New registration
```

**Fill in**:

| Field | Value |
|-------|-------|
| **Name** | `ddh-geoapi-client` (identifies the calling application) |
| **Supported account types** | Accounts in this organizational directory only |
| **Redirect URI** | Leave blank (machines don't use redirects) |

**Click**: Register

#### 3a: Create a Client Secret

The client app needs a password to prove its identity when requesting tokens.

```
On the ddh-geoapi-client app registration:
→ Manage → Certificates & secrets (left sidebar)
→ Client secrets tab
→ + New client secret
```

| Field | Value |
|-------|-------|
| **Description** | `geoapi-b2b-access` |
| **Expires** | 24 months (or per org policy) |

**Click**: Add

**CRITICAL**: Copy the **Value** column immediately. It disappears after you leave this page. The **Secret ID** column is NOT the secret — it's just an identifier for managing the secret later.

#### 3b: What to Give the DDH Team

| Item | Where to find it |
|------|-----------------|
| **Tenant ID** | Any app registration → Overview → Directory (tenant) ID |
| **Client ID** | ddh-geoapi-client → Overview → Application (client) ID |
| **Client Secret** | The Value you just copied |
| **Scope** | `api://{geoapi-gateway-client-id}/.default` |
| **Token endpoint** | `https://login.microsoftonline.com/{tenant-id}/oauth2/v2.0/token` |

With these 5 values, the DDH team can obtain tokens:

```bash
curl -X POST "https://login.microsoftonline.com/{tenant-id}/oauth2/v2.0/token" \
  -d "grant_type=client_credentials" \
  -d "client_id={ddh-client-id}" \
  -d "client_secret={ddh-client-secret}" \
  -d "scope=api://{geoapi-gateway-client-id}/.default"
```

Response: `{"access_token": "eyJ0eX...", "expires_in": 3600, ...}`

They send this token on every API call: `Authorization: Bearer eyJ0eX...`

**Token lifetime**: 60-90 minutes by default. Clients should cache tokens and refresh when expired. Most Azure SDKs (MSAL, azure-identity) handle this automatically.

---

### Step 4: Grant the App Role to the Client

This is where you say "DDH is allowed to call my API." Without this step, DDH can obtain a token, but the token won't have the `Platform.Access` role claim, and Easy Auth will reject it.

**IMPORTANT**: This is done in **Enterprise applications**, not App registrations. They look similar but serve different purposes:
- **App registrations** = the blueprint (what the app is, what roles it defines)
- **Enterprise applications** = the instance (who has access, what roles they have)

```
Azure Portal
→ Microsoft Entra ID
→ Enterprise applications (under "Manage" in left sidebar)
→ Search for: "geoapi-gateway" (YOUR API, not the client)
→ Click on it
```

```
On the geoapi-gateway Enterprise application:
→ Manage → Users and groups (left sidebar)
→ + Add user/group
```

**Assignment form** (3 steps):

**Step A — Select user or group**:
1. Click "None Selected"
2. **IMPORTANT**: You need to switch to the service principals tab. The default view shows users. Look for a tab or filter that shows "Service principals" or "Applications"
3. Search for: `ddh-geoapi-client`
4. Select it
5. Click "Select"

**Step B — Select a role**:
1. Click "None Selected"
2. Choose: `Platform Access`
3. Click "Select"

**Step C**: Click **Assign**

**Result**: DDH's service principal now has `Platform.Access` on your API. Tokens issued to DDH will include this role claim.

**Repeat Step 3 + Step 4 for each additional B2B client.**

---

### Step 5: Security Group (Corporate Environment — Entra ID P1)

In the corporate environment with Entra ID P1, replace per-client role assignment (Step 4) with group-based assignment. This is cleaner for managing multiple clients.

#### 5a: Create the Security Group

```
Azure Portal
→ Microsoft Entra ID
→ Groups (left sidebar)
→ + New group
```

| Field | Value |
|-------|-------|
| **Group type** | Security |
| **Group name** | `GeoAPI-B2B-Clients` |
| **Group description** | Service principals authorized to call /api/platform/* on the Geospatial API |
| **Membership type** | Assigned |

**Click**: Create

#### 5b: Add Client Service Principals to the Group

```
Groups → GeoAPI-B2B-Clients
→ Members (left sidebar)
→ + Add members
→ Search for: "ddh-geoapi-client"
→ Select → Click Add
```

Repeat for each B2B client.

#### 5c: Assign the Group to the API (Replaces Step 4)

```
Enterprise applications → geoapi-gateway
→ Users and groups
→ + Add user/group
→ Select: "GeoAPI-B2B-Clients" group
→ Role: "Platform Access"
→ Assign
```

#### 5d: Enable Assignment Required

This is the "drawbridge up" setting — only explicitly assigned users/groups/service principals can access the app.

```
Enterprise applications → geoapi-gateway
→ Properties (left sidebar)
→ Assignment required? → Yes
→ Save
```

**Result**: Now adding a new B2B client is just:
1. Create their app registration (Step 3)
2. Add their service principal to the `GeoAPI-B2B-Clients` group

No role assignment changes, no app registration changes, no Easy Auth changes.

---

### Step 6: Enable Easy Auth on the Function App

This is where you connect the app registration to the Function App.

```
Azure Portal
→ Resource Groups → rmhazure_rg (or corporate RG)
→ Function App (your gateway app)
→ Settings → Authentication (left sidebar)
→ Add identity provider
```

**Identity provider form**:

| Field | Value | Why |
|-------|-------|-----|
| **Identity provider** | Microsoft | Azure AD / Entra ID |
| **Tenant type** | Workforce | Your organization's directory |
| **App registration** | Pick existing: `geoapi-gateway` | **THIS IS THE CONNECTION** — links Easy Auth to your app registration |
| **Supported account types** | Current tenant - Single tenant | Only your org |
| **Restrict access** | Require authentication | All non-excluded paths need auth |
| **Unauthenticated requests** | HTTP 302 Found redirect | Browser users → MS login. Machines always send tokens so redirect never fires for them. |
| **Token store** | Enabled | Stores session tokens for browser users |

**Click**: Add

**What just happened**: Easy Auth read the `geoapi-gateway` app registration's client ID, tenant ID, and App ID URI. It now knows:
- What tokens to accept (audience = `api://aaaaaaaa-...`)
- Who issued them (your tenant)
- Where to send browser users for login (Microsoft's login page)
- Where they come back after login (the redirect URI from Step 1b)

#### 6a: Configure Excluded Paths

The portal UI does **not** expose the `excludedPaths` setting. You need CLI or ARM.

**Azure CLI** (if available):
```bash
SUBSCRIPTION_ID=$(az account show --query id -o tsv)

az rest --method PUT \
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
            "openIdIssuer": "https://sts.windows.net/{TENANT_ID}/v2.0",
            "clientId": "{GEOAPI_GATEWAY_CLIENT_ID}"
          },
          "validation": {
            "allowedAudiences": [
              "api://{GEOAPI_GATEWAY_CLIENT_ID}"
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

**For corporate eService request**: Include this in the request:
> "We need the following paths excluded from authentication: `/api/health`, `/api/platform/health`, `/api/features/*`, `/api/stac/*`, `/api/dag/*`, `/api/dbadmin/*`, `/api/jobs/*`, `/api/test/*`. This requires the `excludedPaths` property in the authsettingsV2 configuration, which is not available in the portal UI."

#### 6b: What Excluded Paths Mean

| Path | Auth? | Who uses it |
|------|-------|-------------|
| `/api/platform/*` (except /health) | **Yes** | B2B clients, browser interface |
| `/api/platform/health` | No | Load balancers, pre-auth health checks |
| `/api/health` | No | Monitoring, deployment validation |
| `/api/features/*` | No | Public OGC Features API |
| `/api/stac/*` | No | Public STAC catalog |
| `/api/dag/*` | No | Internal DAG status |
| `/api/dbadmin/*` | No | Internal admin tools |
| `/api/jobs/*` | No | Legacy job endpoints |
| `/api/test/*` | No | Test/diagnostic endpoints |

---

### Step 7: Test

#### Test A: Browser Login (your account)

1. Open in browser: `https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/platform/registry`
2. **Expected**: Redirected to Microsoft login page
3. Log in with your Azure AD account
4. **Expected**: Redirected back, see JSON response from registry endpoint
5. Navigate to other `/api/platform/*` endpoints — no re-login (session cookie works)
6. Navigate to `/api/health` — works without login (excluded path)

#### Test B: Machine Client (simulated DDH)

```bash
# 1. Get token
TOKEN=$(curl -s -X POST \
  "https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token" \
  -d "grant_type=client_credentials" \
  -d "client_id={DDH_CLIENT_ID}" \
  -d "client_secret={DDH_CLIENT_SECRET}" \
  -d "scope=api://{GEOAPI_GATEWAY_CLIENT_ID}/.default" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2. Call protected endpoint with token
curl -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/json" \
  "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/platform/registry"
# Expected: 200 OK with JSON

# 3. Call without token
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/platform/registry"
# Expected: 302 redirect to login.microsoftonline.com

# 4. Call excluded path without token
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health"
# Expected: 200 OK (no auth needed)
```

#### Test C: Verify Identity Headers

After a successful authenticated request (Test A or B), check what identity headers Easy Auth injected. Add a temporary test endpoint or check App Insights logs:

```python
# Temporary endpoint to inspect headers (remove after testing)
@app.route(route="platform/debug/identity", methods=["GET"])
def debug_identity(req: func.HttpRequest) -> func.HttpResponse:
    headers = {
        "X-MS-CLIENT-PRINCIPAL-NAME": req.headers.get("X-MS-CLIENT-PRINCIPAL-NAME"),
        "X-MS-CLIENT-PRINCIPAL-ID": req.headers.get("X-MS-CLIENT-PRINCIPAL-ID"),
        "X-MS-CLIENT-PRINCIPAL-IDP": req.headers.get("X-MS-CLIENT-PRINCIPAL-IDP"),
        "X-MS-CLIENT-PRINCIPAL": req.headers.get("X-MS-CLIENT-PRINCIPAL", "")[:100] + "...",
    }
    return func.HttpResponse(json.dumps(headers, indent=2), mimetype="application/json")
```

This resolves **Open Question #2** — what exactly does `X-MS-CLIENT-PRINCIPAL-NAME` contain for machine vs browser auth?

---

### Rollback

To disable Easy Auth without losing the configuration:

```bash
# Read current config first (save it!)
az rest --method GET \
  --uri "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/rmhazure_rg/providers/Microsoft.Web/sites/rmhazuregeoapi/config/authsettingsV2?api-version=2022-03-01" \
  > /tmp/easy_auth_backup.json

# Disable (use the full config body from Step 6a, but change enabled to false)
# The authsettingsV2 endpoint uses PUT (full replacement), NOT PATCH.
# A minimal body will wipe other settings.
```

To disable via portal:
```
Function App → Settings → Authentication
→ Click the identity provider
→ Delete (or toggle off)
```

All endpoints immediately become anonymous again. App registrations and role assignments are preserved — just re-enable Easy Auth to restore protection.

---

## Summary: What Lives Where

| What | Where | Who manages it |
|------|-------|---------------|
| API identity (app registration) | Entra ID → App registrations | IT (eService) |
| Client identities (app registrations) | Entra ID → App registrations | IT (eService) |
| Role assignments | Entra ID → Enterprise applications | IT (eService) |
| Security group | Entra ID → Groups | IT (eService) |
| Easy Auth config | Function App → Authentication | IT or you (portal/CLI) |
| `excludedPaths` | Function App → authsettingsV2 (CLI/ARM) | IT (eService with exact paths) |
| Identity capture code | `infrastructure/platform_auth.py` | You (one function, reads one header) |
| Client phonebook | `app.platform_clients` table | Automatic (lazy-created on first request) |
| Ownership columns | `workflow_runs.submitted_by_app`, `asset_releases.submitted_by_app` | Automatic (written on submit) |
