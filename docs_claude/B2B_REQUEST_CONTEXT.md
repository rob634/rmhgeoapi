# B2B Request Context Tracking (F12.12)

**Created**: 06 FEB 2026
**Status**: PLANNED
**Priority**: MEDIUM - Enables B2B request attribution and audit trail
**Related**: APP_MODE Endpoint Refactor (F12.11), Platform Registry (V0.8)

---

## Problem Statement

Platform/submit and other B2B endpoints don't capture request context. We cannot:
- Identify which B2B client submitted a request (DDH vs internal UI vs other)
- Track user identity for audit purposes
- Correlate requests across systems
- Distinguish Orchestrator UI (admin) from Gateway UI (B2B-facing)

---

## Design Decisions

### 1. Client Identification Strategy

**No API keys or tokens** - identity-based auth only.

| Method | Priority | Source | Reliability | DDH Effort |
|--------|----------|--------|-------------|------------|
| Azure AD token `appid` | **Primary** | JWT claim | High (Azure enforced) | Zero |
| Easy Auth headers | **Primary** | `X-MS-CLIENT-PRINCIPAL-*` | High (Azure enforced) | Zero |
| `User-Agent` | **Fallback** | Standard HTTP header | Medium | Zero |
| `X-Forwarded-For` | Supplemental | Load balancer/APIM | Low (IP only) | Zero |

**Key insight**: Azure AD service-to-service auth includes `appid` claim in the JWT - this uniquely identifies the calling application's Azure AD App Registration. DDH doesn't need to do anything special.

### 2. Storage: Explicit Columns + JSONB Overflow

Extend `ApiRequest` model with explicit columns for known fields, JSONB for extras:

```python
# New fields on ApiRequest model
client_app_id: Optional[str]      # Azure AD appid from JWT (primary identifier)
client_name: Optional[str]        # Resolved name: "ddh", "rmh_orchestrator_ui", etc.
user_identity: Optional[str]      # User email/UPN from Easy Auth (when enabled)
user_object_id: Optional[str]     # Azure AD object ID
correlation_id: Optional[str]     # X-Correlation-Id for request tracing
source_ip: Optional[str]          # X-Forwarded-For
submitted_via: Optional[str]      # Which app received request (gateway/orchestrator)
request_context: Optional[Dict]   # JSONB overflow for unexpected fields
```

### 3. Internal UI Registration

Two internal UIs to identify:

| Client ID | Display Name | App Mode | User-Agent Pattern |
|-----------|--------------|----------|-------------------|
| `rmh_orchestrator_ui` | Orchestrator Admin UI | ORCHESTRATOR | `RMH-Orchestrator-UI/*` |
| `rmh_gateway_ui` | Gateway Platform UI | PLATFORM | `RMH-Gateway-UI/*` |
| `ddh` | Data Distribution Hub | External | DDH's User-Agent or Azure AD appid |

Internal UIs will set `User-Agent` header in JavaScript fetch calls.

---

## Implementation Plan

### Phase 1: Extend ApiRequest Model
**Status**: Pending
**Files**: `core/models/platform.py`

Add new fields to `ApiRequest` class:
```python
client_app_id: Optional[str] = Field(default=None, max_length=64)
client_name: Optional[str] = Field(default=None, max_length=50)
user_identity: Optional[str] = Field(default=None, max_length=255)
user_object_id: Optional[str] = Field(default=None, max_length=64)
correlation_id: Optional[str] = Field(default=None, max_length=64)
source_ip: Optional[str] = Field(default=None, max_length=45)  # IPv6 max
submitted_via: Optional[str] = Field(default=None, max_length=50)
request_context: Optional[Dict[str, Any]] = Field(default=None)
```

Update `PLATFORM_INDEXES` with new index on `client_name`.

### Phase 2: Create Request Context Extractor
**Status**: Pending
**Files**: `services/request_context.py` (NEW)

Create helper module:
```python
def extract_request_context(req: func.HttpRequest) -> RequestContext:
    """Extract client identity and context from HTTP request."""

def _extract_appid_from_token(auth_header: str) -> Optional[str]:
    """Decode JWT and extract appid claim (no signature verification)."""

def _resolve_client_name(context: RequestContext) -> str:
    """Resolve human-readable client name from appid or User-Agent."""
```

### Phase 3: Wire to Platform Submit
**Status**: Pending
**Files**: `triggers/platform/submit.py`

Update `platform_request_submit()`:
1. Call `extract_request_context(req)` early in handler
2. Populate `ApiRequest` with extracted context
3. Pass context to `create_request()`

### Phase 4: Wire to Platform Validate
**Status**: Pending
**Files**: `triggers/trigger_platform_status.py`

Update `platform_validate()` to capture context (even though it doesn't create a job).

### Phase 5: Update Internal UI User-Agents
**Status**: Pending
**Files**: `static/js/*.js` or base template

Add User-Agent header to fetch calls:
```javascript
// In base template or shared JS
const APP_USER_AGENT = '{{ app_mode.app_name }}/{{ version }}';

fetch(url, {
    headers: {
        'User-Agent': APP_USER_AGENT,
        // ... other headers
    }
});
```

### Phase 6: Database Migration
**Status**: Pending
**Files**: Schema auto-generated from Pydantic model

Run `action=ensure` to add new columns:
```bash
curl -X POST ".../api/dbadmin/maintenance?action=ensure&confirm=yes"
```

### Phase 7: Documentation
**Status**: Pending
**Files**: `docs_claude/`, README updates

- Document client registration process (manual SQL for now)
- Document header requirements for external B2B clients
- Update API documentation with new response fields

---

## Client Name Resolution Logic

```python
# Known clients by Azure AD App ID (populate as apps are registered)
CLIENT_APP_IDS = {
    # "abc123-def456-...": "ddh",  # Add when DDH app ID is known
}

# Known clients by User-Agent pattern
CLIENT_USER_AGENTS = [
    (r"RMH-Orchestrator-UI", "rmh_orchestrator_ui"),
    (r"RMH-Gateway-UI", "rmh_gateway_ui"),
    (r"DDH[-/]", "ddh"),
    (r"Python-urllib", "script"),  # Generic Python client
]

def _resolve_client_name(context: RequestContext) -> str:
    # Priority 1: Azure AD App ID (most reliable)
    if context.client_app_id:
        if name := CLIENT_APP_IDS.get(context.client_app_id):
            return name
        return f"app:{context.client_app_id[:8]}"  # Unknown app, show prefix

    # Priority 2: User-Agent pattern
    if context.user_agent:
        for pattern, name in CLIENT_USER_AGENTS:
            if re.search(pattern, context.user_agent, re.I):
                return name

    return "unknown"
```

---

## Easy Auth Integration (Future)

When Easy Auth is enabled on Function Apps:

```python
def _extract_easy_auth_identity(req: func.HttpRequest) -> dict:
    """Extract identity from Easy Auth headers."""
    return {
        'user_object_id': req.headers.get('X-MS-CLIENT-PRINCIPAL-ID'),
        'user_identity': req.headers.get('X-MS-CLIENT-PRINCIPAL-NAME'),
        'identity_provider': req.headers.get('X-MS-CLIENT-PRINCIPAL-IDP'),
    }
```

Easy Auth automatically validates tokens and exposes claims as headers. No manual JWT decoding needed when enabled.

---

## Testing Plan

### Test 1: Internal UI Identification
1. Submit job via Orchestrator UI
2. Verify `client_name = "rmh_orchestrator_ui"` in api_requests
3. Submit job via Gateway UI
4. Verify `client_name = "rmh_gateway_ui"` in api_requests

### Test 2: DDH Identification (User-Agent)
1. Submit job with `User-Agent: DDH-Client/2.0`
2. Verify `client_name = "ddh"` in api_requests

### Test 3: Azure AD App Identification (when available)
1. Submit job with Azure AD Bearer token
2. Verify `client_app_id` extracted from token
3. Verify `client_name` resolved from app ID mapping

### Test 4: Unknown Client Fallback
1. Submit job with unknown User-Agent
2. Verify `client_name = "unknown"` (or shows app ID prefix if available)

---

## SQL Verification

```sql
-- Check client distribution
SELECT client_name, COUNT(*)
FROM app.api_requests
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY client_name;

-- Find requests from specific client
SELECT request_id, dataset_id, job_id, created_at
FROM app.api_requests
WHERE client_name = 'ddh'
ORDER BY created_at DESC
LIMIT 20;

-- Find requests with correlation ID
SELECT * FROM app.api_requests
WHERE correlation_id = 'req-abc123';
```

---

## Rollback Plan

If issues arise:
1. New columns are nullable - existing code continues to work
2. Can remove extraction logic without data loss
3. JSONB overflow captures anything we miss

---

## Success Criteria

1. All platform/submit requests capture `client_name`
2. Internal UIs identified distinctly from external B2B
3. Correlation ID captured when provided
4. No breaking changes to existing API contracts
5. Query able to answer "show all requests from DDH this week"
