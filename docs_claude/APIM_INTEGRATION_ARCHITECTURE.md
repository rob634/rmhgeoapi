# API Management (APIM) Integration Architecture

**Date**: 25 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Define how Azure API Management integrates with the Platform Service

## Architecture with APIM

```
┌─────────────────────────────────────────────────────────┐
│                 External Applications                    │
│         (DDH, Analytics Apps, Partner Systems)           │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│              Azure API Management (APIM)                 │
│                                                          │
│  • Authentication & Authorization                        │
│  • Rate Limiting & Throttling                           │
│  • Request/Response Transformation                       │
│  • API Versioning                                       │
│  • Analytics & Monitoring                               │
│  • Developer Portal                                     │
│  • Caching                                              │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│           Platform Service (Function App)                │
│                                                          │
│  • Process requests from APIM                           │
│  • No longer handles auth directly                      │
│  • Trusts APIM headers                                  │
│  • Returns standardized responses                       │
└─────────────────────────────────────────────────────────┘
```

## APIM Configuration

### 1. API Products and Subscriptions

```xml
<!-- APIM Product Definition -->
<products>
    <!-- DDH Product (Primary Client) -->
    <product name="DDH-Platform-API" displayName="DDH Data Platform">
        <description>Data processing platform for DDH</description>
        <terms>Internal use only</terms>
        <subscriptionRequired>true</subscriptionRequired>
        <approvalRequired>false</approvalRequired>
        <subscriptionsLimit>1</subscriptionsLimit>
        <state>published</state>
        <groups>
            <group name="ddh-developers"/>
        </groups>
        <apis>
            <api name="platform-api-v1"/>
            <api name="stac-api-internal"/>
        </apis>
        <policies>
            <rateLimit calls="1000" renewal-period="60"/>
            <quota calls="100000" renewal-period="86400"/>
        </policies>
    </product>

    <!-- Partner Product (Future) -->
    <product name="Partner-Platform-API" displayName="Partner Access">
        <description>Limited platform access for partners</description>
        <subscriptionRequired>true</subscriptionRequired>
        <approvalRequired>true</approvalRequired>
        <state>published</state>
        <apis>
            <api name="platform-api-v1-limited"/>
        </apis>
        <policies>
            <rateLimit calls="100" renewal-period="60"/>
            <quota calls="10000" renewal-period="86400"/>
        </policies>
    </product>

    <!-- Public Product (Restricted) -->
    <product name="Public-Data-API" displayName="Public Data Access">
        <description>Public access to published datasets</description>
        <subscriptionRequired>false</subscriptionRequired>
        <state>published</state>
        <apis>
            <api name="data-api-public"/>
        </apis>
        <policies>
            <rateLimit calls="10" renewal-period="60"/>
            <ip-filter action="allow">
                <address-range from="0.0.0.0" to="255.255.255.255"/>
            </ip-filter>
        </policies>
    </product>
</products>
```

### 2. API Definitions

```yaml
# platform-api-v1.yaml
openapi: 3.0.1
info:
  title: Platform Processing API
  version: v1
servers:
  - url: https://api.yourplatform.com/v1
paths:
  /process:
    post:
      summary: Submit processing request
      operationId: submitProcessingRequest
      x-ms-apim-backend-id: platform-function-app
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/ProcessingRequest'
      responses:
        '202':
          description: Accepted for processing
          headers:
            Location:
              schema:
                type: string
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ProcessingResponse'

  /status/{requestId}:
    get:
      summary: Check processing status
      operationId: getProcessingStatus
      parameters:
        - name: requestId
          in: path
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Status information
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/StatusResponse'
```

### 3. APIM Policies

#### Inbound Processing Policy

```xml
<policies>
    <inbound>
        <!-- Extract and validate subscription key -->
        <validate-subscription-key header-name="Ocp-Apim-Subscription-Key" />

        <!-- Extract client information -->
        <set-header name="X-Client-Id" exists-action="override">
            <value>@(context.Subscription?.Name ?? "unknown")</value>
        </set-header>

        <!-- Add correlation ID for tracing -->
        <set-header name="X-Correlation-Id" exists-action="skip">
            <value>@(Guid.NewGuid().ToString())</value>
        </set-header>

        <!-- Transform DDH-specific fields if needed -->
        <choose>
            <when condition="@(context.Request.Headers.GetValueOrDefault("X-Client-Id","") == "ddh_v1")">
                <set-body>@{
                    var body = context.Request.Body.As<JObject>();
                    // Add DDH-specific transformations
                    body["client_id"] = "ddh_v1";
                    body["priority"] = "high";
                    return body.ToString();
                }</set-body>
            </when>
        </choose>

        <!-- Rate limiting by subscription -->
        <rate-limit-by-key
            calls="100"
            renewal-period="60"
            counter-key="@(context.Subscription?.Key ?? "anonymous")" />

        <!-- Cache key for GET requests -->
        <cache-lookup vary-by-developer="false" vary-by-developer-groups="false">
            <vary-by-header>Accept</vary-by-header>
            <vary-by-query-parameter>*</vary-by-query-parameter>
        </cache-lookup>
    </inbound>

    <backend>
        <!-- Forward to Function App -->
        <base />
    </backend>

    <outbound>
        <!-- Add CORS headers -->
        <cors>
            <allowed-origins>
                <origin>https://ddh.application.com</origin>
            </allowed-origins>
            <allowed-methods>
                <method>GET</method>
                <method>POST</method>
                <method>OPTIONS</method>
            </allowed-methods>
            <allowed-headers>
                <header>*</header>
            </allowed-headers>
        </cors>

        <!-- Transform response for client -->
        <choose>
            <when condition="@(context.Response.StatusCode == 202)">
                <!-- Add full URL to Location header -->
                <set-header name="Location" exists-action="override">
                    <value>@{
                        var location = context.Response.Headers.GetValueOrDefault("Location","");
                        return $"https://api.yourplatform.com/v1{location}";
                    }</value>
                </set-header>
            </when>
        </choose>

        <!-- Cache responses -->
        <cache-store duration="300" />

        <!-- Add response headers -->
        <set-header name="X-Powered-By" exists-action="override">
            <value>Platform Service v1</value>
        </set-header>
    </outbound>

    <on-error>
        <!-- Sanitize error responses -->
        <set-body>@{
            return new JObject(
                new JProperty("error", context.LastError.Message),
                new JProperty("requestId", context.Request.Headers.GetValueOrDefault("X-Correlation-Id", "")),
                new JProperty("timestamp", DateTime.UtcNow.ToString("o"))
            ).ToString();
        }</set-body>
        <set-header name="Content-Type" exists-action="override">
            <value>application/json</value>
        </set-header>
    </on-error>
</policies>
```

## Platform Service Adjustments for APIM

### 1. Trust APIM Headers

```python
# platform/auth.py

class APIMAuth:
    """Handle authentication from APIM headers"""

    # APIM will add these headers after validation
    APIM_HEADERS = {
        "X-Client-Id": "Client identifier from APIM",
        "X-Subscription-Name": "APIM subscription name",
        "X-Correlation-Id": "Request correlation ID",
        "X-Product-Name": "APIM product name",
        "X-Rate-Limit-Remaining": "Remaining calls"
    }

    @staticmethod
    def extract_client_info(request: func.HttpRequest) -> ClientInfo:
        """Extract client information from APIM headers"""

        # APIM has already authenticated - we just extract
        return ClientInfo(
            client_id=request.headers.get("X-Client-Id", "unknown"),
            subscription=request.headers.get("X-Subscription-Name"),
            correlation_id=request.headers.get("X-Correlation-Id"),
            product=request.headers.get("X-Product-Name"),
            rate_limit_remaining=request.headers.get("X-Rate-Limit-Remaining")
        )

    @staticmethod
    def is_from_apim(request: func.HttpRequest) -> bool:
        """Verify request came through APIM"""

        # Check for APIM-specific headers or IP
        apim_signature = request.headers.get("X-APIM-Request-Id")

        # Optionally verify APIM IP addresses
        client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0]
        apim_ips = ["40.112.72.205", "13.91.254.72"]  # Your APIM IPs

        return apim_signature is not None or client_ip in apim_ips
```

### 2. Simplified Platform Endpoints

```python
# Updated function_app.py endpoints for APIM

@app.route(route="process", methods=["POST"])
def platform_process(req: func.HttpRequest) -> func.HttpResponse:
    """
    Process request - APIM has already handled auth.
    """
    # Verify request is from APIM
    if not APIMAuth.is_from_apim(req):
        return func.HttpResponse(status_code=403)

    # Extract client info from APIM headers
    client_info = APIMAuth.extract_client_info(req)

    # Log with correlation ID
    logger.info(f"[{client_info.correlation_id}] Processing request from {client_info.client_id}")

    # Process request (auth already done by APIM)
    request = ProcessingRequest.model_validate_json(req.get_body())
    response = platform_router.process_request(request, client_info)

    return func.HttpResponse(
        response.model_dump_json(),
        status_code=202,
        headers={
            "Location": f"/status/{response.request_id}"
        }
    )

@app.route(route="status/{request_id}", methods=["GET"])
def platform_status(req: func.HttpRequest) -> func.HttpResponse:
    """
    Status check - can be cached by APIM.
    """
    # Extract from APIM headers
    client_info = APIMAuth.extract_client_info(req)
    request_id = req.route_params.get('request_id')

    # Get status (with client validation)
    status = platform_service.get_status(request_id, client_info.client_id)

    if not status:
        return func.HttpResponse(status_code=404)

    # Add cache headers for APIM
    return func.HttpResponse(
        status.model_dump_json(),
        headers={
            "Cache-Control": "public, max-age=10" if status.is_processing else "no-cache",
            "ETag": f'"{status.version}"'
        }
    )
```

### 3. APIM-Specific Response Formats

```python
class APIMResponse(BaseModel):
    """Standardized response format for APIM"""

    # Standard fields APIM expects
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None

    # Metadata for APIM analytics
    metadata: Dict[str, Any] = {
        "version": "1.0",
        "timestamp": datetime.utcnow().isoformat()
    }

    # Links for HATEOAS
    links: Dict[str, str] = {}
```

## APIM Benefits for Platform Service

### 1. Security
- **Subscription keys** managed by APIM
- **OAuth 2.0** support without code changes
- **IP whitelisting** at APIM level
- **DDoS protection** built-in

### 2. Operations
- **Rate limiting** without code
- **Response caching** reduces load
- **Request/response transformation**
- **API versioning** (v1, v2 side-by-side)

### 3. Analytics
- **Usage metrics** per client
- **Performance monitoring**
- **Error tracking**
- **Cost allocation** by subscription

### 4. Developer Experience
- **Developer portal** for documentation
- **Interactive API console**
- **Subscription self-service**
- **OpenAPI/Swagger** auto-generation

## APIM Configuration for Different Clients

### DDH Configuration
```json
{
    "subscription": "ddh-production",
    "product": "DDH-Platform-API",
    "policies": {
        "rateLimit": "1000/minute",
        "quota": "100000/day",
        "caching": "enabled",
        "transformation": "ddh-transform-policy"
    },
    "backends": [
        "platform-function-app-primary",
        "platform-function-app-secondary"
    ]
}
```

### Partner Configuration
```json
{
    "subscription": "partner-limited",
    "product": "Partner-Platform-API",
    "policies": {
        "rateLimit": "100/minute",
        "quota": "10000/day",
        "ipFilter": "partner-ip-whitelist",
        "responseFilter": "remove-internal-fields"
    }
}
```

## Implementation Changes

### What Changes:
1. **Remove auth from Function App** - APIM handles it
2. **Trust APIM headers** - Client info comes from APIM
3. **Simplify error handling** - APIM sanitizes errors
4. **Add cache headers** - APIM can cache responses

### What Doesn't Change:
1. **Core logic** - Same processing workflow
2. **Database** - Same platform schema
3. **CoreMachine** - Unchanged
4. **STAC generation** - Same process

## APIM Deployment Strategy

### Phase 1: Basic Setup
1. Create APIM instance
2. Import OpenAPI definition
3. Configure DDH subscription
4. Set up basic policies

### Phase 2: Advanced Features
1. Response caching
2. Request transformation
3. Multiple backends
4. Failover configuration

### Phase 3: Monitoring
1. Application Insights integration
2. Custom metrics
3. Alert rules
4. Usage reports

## Testing with APIM

### Local Development
```python
# Simulate APIM headers for local testing
if os.getenv("ENVIRONMENT") == "local":
    def add_apim_headers(request):
        request.headers["X-Client-Id"] = "test-client"
        request.headers["X-Correlation-Id"] = str(uuid.uuid4())
        request.headers["X-Subscription-Name"] = "dev-subscription"
        return request
```

### Integration Testing
1. Test with APIM dev instance
2. Validate rate limiting
3. Check caching behavior
4. Verify transformations

## Benefits of APIM Integration

### For DDH:
- Stable API endpoint (APIM URL never changes)
- Built-in retry and circuit breaker
- Response caching for better performance

### For Platform Service:
- No auth code to maintain
- Automatic rate limiting
- Built-in analytics
- Easy versioning

### For Future Clients:
- Self-service onboarding
- Different rate limits per client
- Custom transformations
- Separate products/pricing

This architecture ensures your Platform Service focuses on processing while APIM handles all cross-cutting concerns!