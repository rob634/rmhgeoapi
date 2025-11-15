# Azure Easy Auth Setup Guide

**Author**: Robert and Geospatial Claude Legion
**Date**: 14 NOV 2025
**Status**: ✅ TESTED AND WORKING
**Function App**: rmhazuregeoapi (B3 Basic tier)

---

## 🎯 Overview

This guide documents how to enable **Azure App Service Easy Auth** (Authentication/Authorization) for the geospatial ETL function app. Easy Auth provides **zero-code authentication** - all configuration is done at the platform level via Azure Portal or CLI.

**What Easy Auth Provides**:
- ✅ Platform-managed authentication (no code changes required)
- ✅ Automatic token management and session storage
- ✅ User identity headers injected into all requests
- ✅ Support for multiple identity providers (Microsoft, Google, GitHub, etc.)
- ✅ Logout endpoints provided automatically
- ✅ Integration with Azure AD, MS Authenticator, and enterprise SSO

**Current Configuration**:
- **Provider**: Microsoft (Azure AD / Entra ID)
- **Tenant**: Personal Azure subscription (`086aef7e-db12-4161-8a9f-777deb499cfa`)
- **User**: `rmhazure@rob634gmail.onmicrosoft.com`
- **App Registration**: `rmhazuregeoapi-easyauth`
- **Access**: Single-tenant (only users in your Azure AD tenant)

---

## 🔧 Method 1: Azure Portal Setup (Recommended for First-Time)

### Step 1: Navigate to Authentication Settings

**Azure Portal Path**:
```
Azure Portal (portal.azure.com)
→ Resource Groups
→ rmhazure_rg
→ rmhazuregeoapi (Function App)
→ Settings
→ Authentication
```

### Step 2: Add Identity Provider

**Click**: "Add identity provider"

**Provider Selection**:
- Choose: **Microsoft**

### Step 3: Configure Microsoft Identity Provider

**Basic Settings**:

1. **Tenant type**:
   - Select: **Workforce** (for Azure AD / Entra ID)
   - This uses your Azure AD tenant for authentication

2. **App registration**:
   - **Option A - Create new** (Recommended for first-time):
     - Select: "Create new app registration"
     - App registration name: `rmhazuregeoapi-easyauth`
     - Supported account types: **"Accounts in this organizational directory only (Single tenant)"**
     - Portal will automatically create the app and configure redirect URIs

   - **Option B - Use existing** (If you already have an app registration):
     - Select: "Pick an existing app registration in this directory"
     - Choose: `rmhazuregeoapi-easyauth` (or your existing app)

3. **Issuer URL**: (Auto-populated)
   ```
   https://sts.windows.net/{YOUR_TENANT_ID}/
   ```
   Example: `https://sts.windows.net/086aef7e-db12-4161-8a9f-777deb499cfa/`

**Client Application Requirement**:

4. **Restrict access**:
   - Select: ✅ **"Require authentication"**
   - This makes all endpoints require login

5. **Unauthenticated requests**:
   - Select: **"HTTP 302 Found redirect: recommended for websites"**
   - This redirects unauthenticated users to Microsoft login page

**Token Configuration**:

6. **Token store**:
   - ✅ **Enable** (Recommended)
   - Stores authentication tokens in cookies for session management
   - Session timeout: 8 hours (default)

7. **Allowed token audiences** (Advanced):
   - Usually leave default (auto-configured)
   - If needed, add:
     - `api://{CLIENT_ID}`
     - `https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net`

**Click**: "Add"

### Step 4: Verify Configuration

**Portal View**:
```
Authentication page should show:
- Identity provider: Microsoft
- Status: Enabled ✅
- Require authentication: Yes
```

**Test immediately**:
```
Open in browser:
https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health
```

**Expected behavior**:
1. Redirects to Microsoft login page
2. Login with your Azure AD account
3. May prompt for MS Authenticator approval (if configured)
4. After login, redirects back to function app
5. Shows health endpoint JSON response

---

## 💻 Method 2: Azure CLI Setup (Faster for Automation)

### Prerequisites

**Verify Azure CLI login**:
```bash
az login
az account show --query "{subscription:name, user:user.name, tenant:tenantId}" -o table
```

**Expected output**:
```
Subscription    User                                  Tenant
--------------  ------------------------------------  ------------------------------------
rmhazure        rmhazure@rob634gmail.onmicrosoft.com  086aef7e-db12-4161-8a9f-777deb499cfa
```

### Step 1: Create App Registration

**Create new Azure AD app registration**:
```bash
az ad app create \
  --display-name "rmhazuregeoapi-easyauth" \
  --sign-in-audience AzureADMyOrg \
  --web-redirect-uris "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/.auth/login/aad/callback" \
  --enable-id-token-issuance true \
  --enable-access-token-issuance true \
  --query "{AppId:appId, DisplayName:displayName}" \
  -o table
```

**Output**:
```
AppId                                 DisplayName
------------------------------------  -----------------------
8c0d412b-f7b1-4920-8a5f-22f8ae9903e9  rmhazuregeoapi-easyauth
```

**Copy the AppId** - you'll need it in the next step.

### Step 2: Set Application ID URI

**Configure identifier URI**:
```bash
az ad app update \
  --id 8c0d412b-f7b1-4920-8a5f-22f8ae9903e9 \
  --identifier-uris "api://8c0d412b-f7b1-4920-8a5f-22f8ae9903e9"
```

### Step 3: Enable Easy Auth on Function App

**Configure authentication with v1 API** (simpler):
```bash
az webapp auth update \
  --name rmhazuregeoapi \
  --resource-group rmhazure_rg \
  --enabled true \
  --action LoginWithAzureActiveDirectory \
  --aad-client-id "8c0d412b-f7b1-4920-8a5f-22f8ae9903e9" \
  --aad-token-issuer-url "https://sts.windows.net/086aef7e-db12-4161-8a9f-777deb499cfa/" \
  --aad-allowed-token-audiences "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/.auth/login/aad/callback" \
  --token-store true
```

**Or use v2 API** (recommended for production):
```bash
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
TENANT_ID="086aef7e-db12-4161-8a9f-777deb499cfa"
CLIENT_ID="8c0d412b-f7b1-4920-8a5f-22f8ae9903e9"

az rest \
  --method PUT \
  --uri "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/rmhazure_rg/providers/Microsoft.Web/sites/rmhazuregeoapi/config/authsettingsV2?api-version=2022-03-01" \
  --headers "Content-Type=application/json" \
  --body "{
    \"properties\": {
      \"platform\": {
        \"enabled\": true
      },
      \"globalValidation\": {
        \"requireAuthentication\": true,
        \"unauthenticatedClientAction\": \"RedirectToLoginPage\",
        \"redirectToProvider\": \"azureactivedirectory\"
      },
      \"identityProviders\": {
        \"azureActiveDirectory\": {
          \"enabled\": true,
          \"registration\": {
            \"openIdIssuer\": \"https://sts.windows.net/$TENANT_ID/v2.0\",
            \"clientId\": \"$CLIENT_ID\"
          },
          \"validation\": {
            \"allowedAudiences\": [
              \"api://$CLIENT_ID\",
              \"https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net\"
            ]
          }
        }
      },
      \"login\": {
        \"tokenStore\": {
          \"enabled\": true
        }
      }
    }
  }"
```

### Step 4: Verify Configuration

**Check auth status**:
```bash
az webapp auth show \
  --name rmhazuregeoapi \
  --resource-group rmhazure_rg \
  --query "{enabled:enabled, provider:defaultProvider, clientId:clientId, tokenStoreEnabled:tokenStoreEnabled}" \
  -o table
```

**Expected output**:
```
Enabled    DefaultProvider       ClientId                              TokenStoreEnabled
---------  --------------------  ------------------------------------  -------------------
True       AzureActiveDirectory  8c0d412b-f7b1-4920-8a5f-22f8ae9903e9  True
```

---

## 🧪 Testing Authentication

### Test 1: Browser Login Flow

**Open function app URL**:
```
https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health
```

**Expected Flow**:
1. **Redirect to Microsoft login**
   - URL: `https://login.microsoftonline.com/...`

2. **Login screen**
   - Enter: `rmhazure@rob634gmail.onmicrosoft.com`
   - (Or your Azure AD account)

3. **MS Authenticator prompt** (if configured)
   - Approve via mobile app push notification
   - Or enter code from authenticator app

4. **Redirect back to function app**
   - URL: `https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health`
   - Shows: Health endpoint JSON response

5. **Session persisted**
   - Navigate to other endpoints - no re-login needed
   - Session lasts 8 hours (default)

### Test 2: Verify Injected Headers

**Browser DevTools**:
```
1. Open DevTools (F12)
2. Network tab
3. Reload page
4. Click on /api/health request
5. Headers tab → Request Headers
```

**Look for Easy Auth headers**:
```
X-MS-CLIENT-PRINCIPAL-NAME: rmhazure@rob634gmail.onmicrosoft.com
X-MS-CLIENT-PRINCIPAL-ID: {your-user-guid}
X-MS-CLIENT-PRINCIPAL-IDP: aad
X-MS-TOKEN-AAD-ACCESS-TOKEN: eyJ0eXAiOiJKV1QiLCJhbGc...
```

**These headers are automatically available to your Python code** (no changes needed):
```python
# In any function endpoint (future code enhancement)
def my_endpoint(req: func.HttpRequest) -> func.HttpResponse:
    user_email = req.headers.get('X-MS-CLIENT-PRINCIPAL-NAME')
    user_id = req.headers.get('X-MS-CLIENT-PRINCIPAL-ID')

    logger.info(f"Request from user: {user_email}")
    # Continue with normal logic...
```

### Test 3: Test Multiple Endpoints

**All endpoints should work after single login**:

```bash
# STAC API
https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/stac/collections

# OGC Features API
https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/features/collections

# Admin endpoints
https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/db/schemas

# Vector viewer
https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/vector/viewer?collection=test
```

**Expected**: All work without additional login prompts

### Test 4: Logout Flow

**Logout URL** (automatically provided by Easy Auth):
```
https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/.auth/logout
```

**Behavior**:
1. Clears session cookies
2. Redirects to Microsoft logout
3. Next visit to function app → requires login again

**Test**:
```
1. While logged in, navigate to /.auth/logout
2. After logout, try accessing /api/health
3. Should redirect to Microsoft login screen
```

### Test 5: curl Access (Requires Token)

**curl won't work without cookies/token**:
```bash
# This will return 401 Unauthorized
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health
```

**Expected**:
```
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Bearer realm="rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net"
```

**To use with curl** (advanced):
1. Extract cookies from browser session, OR
2. Get Azure AD token via `az login` and pass in Authorization header

**Not recommended for testing** - use browser instead.

---

## 🔧 Management & Troubleshooting

### Check Current Auth Status

```bash
az webapp auth show \
  --name rmhazuregeoapi \
  --resource-group rmhazure_rg \
  --query "{enabled:enabled, provider:defaultProvider, clientId:clientId}" \
  -o table
```

### Disable Authentication (Rollback)

**Temporary disable** (keeps configuration):
```bash
az webapp auth update \
  --name rmhazuregeoapi \
  --resource-group rmhazure_rg \
  --enabled false
```

**After disabling**:
- All endpoints immediately accessible without login
- Configuration preserved (can re-enable with `--enabled true`)

### Re-enable Authentication

```bash
az webapp auth update \
  --name rmhazuregeoapi \
  --resource-group rmhazure_rg \
  --enabled true
```

### View App Registration Details

```bash
az ad app show \
  --id 8c0d412b-f7b1-4920-8a5f-22f8ae9903e9 \
  --query "{AppId:appId, DisplayName:displayName, RedirectUris:web.redirectUris, IdentifierUris:identifierUris}" \
  -o json
```

### Delete App Registration (Full Cleanup)

**Warning**: This removes the app registration entirely. You'll need to create a new one to re-enable auth.

```bash
az ad app delete --id 8c0d412b-f7b1-4920-8a5f-22f8ae9903e9
```

**Then disable Easy Auth**:
```bash
az webapp auth update \
  --name rmhazuregeoapi \
  --resource-group rmhazure_rg \
  --enabled false
```

---

## 🐛 Troubleshooting Common Issues

### Issue 1: "Redirect URI Mismatch" Error

**Symptoms**:
- Login fails with error: `AADSTS50011: The redirect URI specified in the request does not match...`

**Cause**:
- Redirect URI in App Registration doesn't match Easy Auth callback URL

**Fix**:
```bash
# Update App Registration redirect URI
az ad app update \
  --id 8c0d412b-f7b1-4920-8a5f-22f8ae9903e9 \
  --web-redirect-uris "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/.auth/login/aad/callback"
```

**Verify**:
```bash
az ad app show \
  --id 8c0d412b-f7b1-4920-8a5f-22f8ae9903e9 \
  --query "web.redirectUris"
```

### Issue 2: "Invalid Audience" Error

**Symptoms**:
- Login succeeds but then shows error about token audience

**Cause**:
- Token audience doesn't match allowed audiences in Easy Auth

**Fix**:
```bash
# Update allowed token audiences
az webapp auth update \
  --name rmhazuregeoapi \
  --resource-group rmhazure_rg \
  --enabled true \
  --aad-allowed-token-audiences \
    "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/.auth/login/aad/callback" \
    "api://8c0d412b-f7b1-4920-8a5f-22f8ae9903e9"
```

### Issue 3: Implicit Grant Flow Not Enabled

**Symptoms**:
- Callback error after login
- Error about token issuance

**Cause**:
- App Registration not configured to issue ID tokens and access tokens

**Fix**:
```bash
az ad app update \
  --id 8c0d412b-f7b1-4920-8a5f-22f8ae9903e9 \
  --enable-id-token-issuance true \
  --enable-access-token-issuance true
```

**Verify**:
```bash
az ad app show \
  --id 8c0d412b-f7b1-4920-8a5f-22f8ae9903e9 \
  --query "web.implicitGrantSettings"
```

**Expected**:
```json
{
  "enableAccessTokenIssuance": true,
  "enableIdTokenIssuance": true
}
```

### Issue 4: Session Expired

**Symptoms**:
- Randomly redirected to login after being logged in

**Cause**:
- Token expired (default: 8 hours)

**Fix** (extend session timeout):
```bash
# Via v2 API - set to 24 hours
az rest \
  --method PUT \
  --uri "/subscriptions/$(az account show --query id -o tsv)/resourceGroups/rmhazure_rg/providers/Microsoft.Web/sites/rmhazuregeoapi/config/authsettingsV2?api-version=2022-03-01" \
  --headers "Content-Type=application/json" \
  --body '{
    "properties": {
      "login": {
        "cookieExpiration": {
          "convention": "FixedTime",
          "timeToExpiration": "24:00:00"
        }
      }
    }
  }'
```

### Issue 5: Can't Access from CLI/Scripts

**Symptoms**:
- `curl` returns 401 Unauthorized

**Cause**:
- CLI tools don't have browser cookies

**Solution A - Use Browser**:
- Easy Auth is designed for browser-based access
- Use browser for testing

**Solution B - Get Token** (advanced):
```bash
# Get Azure AD token
az login
TOKEN=$(az account get-access-token \
  --resource api://8c0d412b-f7b1-4920-8a5f-22f8ae9903e9 \
  --query accessToken -o tsv)

# Use token in curl
curl -H "Authorization: Bearer $TOKEN" \
  https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health
```

**Solution C - Disable Auth for Testing**:
```bash
# Temporarily disable auth
az webapp auth update \
  --name rmhazuregeoapi \
  --resource-group rmhazure_rg \
  --enabled false

# Test with curl (no auth needed)
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health

# Re-enable auth
az webapp auth update \
  --name rmhazuregeoapi \
  --resource-group rmhazure_rg \
  --enabled true
```

---

## 🚀 Production Deployment (World Bank)

### Key Differences from Dev Setup

**Dev (Current)**:
- Personal Azure subscription
- Single-tenant: Your account only
- Tenant: `086aef7e-db12-4161-8a9f-777deb499cfa`

**Production (World Bank)**:
- Enterprise Azure subscription
- Multi-tenant: All World Bank employees
- Tenant: World Bank Azure AD tenant ID
- Group-based restrictions available (Azure AD Premium)

### Production Setup Steps

**Same process, different values**:

1. **Create App Registration** (World Bank tenant):
   ```bash
   az ad app create \
     --display-name "geospatial-api-easyauth" \
     --sign-in-audience AzureADMyOrg \
     --web-redirect-uris "https://geospatial.worldbank.org/.auth/login/aad/callback"
   ```

2. **Configure Easy Auth** (World Bank tenant):
   ```bash
   az webapp auth update \
     --name geospatial-api \
     --resource-group worldbank_geo_rg \
     --enabled true \
     --action LoginWithAzureActiveDirectory \
     --aad-client-id "{WORLD_BANK_APP_ID}" \
     --aad-token-issuer-url "https://sts.windows.net/{WORLD_BANK_TENANT_ID}/" \
     --token-store true
   ```

3. **Restrict to Specific Groups** (Azure AD Premium):
   - Azure Portal → Enterprise Applications
   - Select: `geospatial-api-easyauth`
   - Users and groups → Add user/group
   - Select: "GeoAdmins", "DataCurators", etc.
   - Only members of selected groups can access

### Optional: Email Whitelist in Code

**If group-based restrictions not available** (non-Premium tenant):

Create `utils/auth.py`:
```python
# utils/auth.py
import azure.functions as func
from typing import Optional

ADMIN_EMAILS = [
    'robert.harrison@worldbank.org',
    'data.curator@worldbank.org',
    # Add authorized users
]

def get_authenticated_user(req: func.HttpRequest) -> Optional[str]:
    """Extract authenticated user email from Easy Auth headers."""
    return req.headers.get('X-MS-CLIENT-PRINCIPAL-NAME')

def is_admin(req: func.HttpRequest) -> bool:
    """Check if user is in admin whitelist."""
    user_email = get_authenticated_user(req)
    return user_email in ADMIN_EMAILS

def require_admin(handler):
    """Decorator to restrict endpoint to admin users."""
    from functools import wraps

    @wraps(handler)
    def wrapper(req: func.HttpRequest) -> func.HttpResponse:
        if not is_admin(req):
            return func.HttpResponse(
                json.dumps({'error': 'Unauthorized', 'message': 'Admin access required'}),
                status_code=403,
                mimetype='application/json'
            )
        return handler(req)

    return wrapper
```

**Apply to admin endpoints**:
```python
# function_app.py
from utils.auth import require_admin

@app.route(route="db/schemas", methods=["GET"])
@require_admin
def db_schemas_list(req: func.HttpRequest) -> func.HttpResponse:
    """Admin-only endpoint."""
    return admin_db_schemas_trigger.handle_request(req)
```

---

## 📋 Quick Reference

### URLs

**Function App**:
```
https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net
```

**Login Endpoint** (automatic redirect):
```
https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/.auth/login/aad
```

**Logout Endpoint**:
```
https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/.auth/logout
```

**Callback URL** (for App Registration):
```
https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/.auth/login/aad/callback
```

### Identifiers

**Tenant ID**:
```
086aef7e-db12-4161-8a9f-777deb499cfa
```

**App Registration**:
- Name: `rmhazuregeoapi-easyauth`
- Client ID: `8c0d412b-f7b1-4920-8a5f-22f8ae9903e9`
- Identifier URI: `api://8c0d412b-f7b1-4920-8a5f-22f8ae9903e9`

**Authenticated User**:
```
rmhazure@rob634gmail.onmicrosoft.com
```

### Headers Available in Code

**After authentication, these headers are automatically available**:

```python
X-MS-CLIENT-PRINCIPAL-NAME  # User email
X-MS-CLIENT-PRINCIPAL-ID    # User GUID
X-MS-CLIENT-PRINCIPAL-IDP   # Identity provider (aad)
X-MS-TOKEN-AAD-ACCESS-TOKEN # Access token (if needed)
X-MS-TOKEN-AAD-ID-TOKEN     # ID token (if needed)
```

---

## 🎯 Benefits Summary

**What Easy Auth Gives You**:
- ✅ **Zero code changes** - Pure configuration
- ✅ **Platform-managed** - Microsoft handles token validation, encryption, session storage
- ✅ **Automatic headers** - User identity available in all endpoints
- ✅ **Enterprise SSO** - Works with Azure AD, MS Authenticator, Conditional Access
- ✅ **Audit trail** - All access logged with user identity
- ✅ **Session management** - 8-hour sessions (configurable)
- ✅ **Logout support** - Built-in logout endpoint
- ✅ **CORS-friendly** - Works with browser apps (with credentials: 'include')

**What You Still Control**:
- User whitelists (in code)
- Endpoint-level restrictions (decorators)
- Business logic authorization
- Rate limiting per user
- Custom claims/roles validation

---

## 📚 References

**Microsoft Documentation**:
- [Easy Auth Overview](https://docs.microsoft.com/en-us/azure/app-service/overview-authentication-authorization)
- [Azure AD Authentication](https://docs.microsoft.com/en-us/azure/app-service/configure-authentication-provider-aad)
- [Authentication Flow](https://docs.microsoft.com/en-us/azure/app-service/overview-authentication-authorization#authentication-flow)

**Azure CLI References**:
- [`az webapp auth`](https://docs.microsoft.com/en-us/cli/azure/webapp/auth)
- [`az ad app`](https://docs.microsoft.com/en-us/cli/azure/ad/app)

**Related Docs**:
- `CLAUDE_CONTEXT.md` - Primary context for function app
- `DEPLOYMENT_GUIDE.md` - Deployment procedures
- `TODO.md` - Active task list

---

**Last Updated**: 14 NOV 2025
**Tested On**: rmhazuregeoapi (B3 Basic tier)
**Status**: ✅ Working in production