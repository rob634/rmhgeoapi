# Platform Layer OpenAPI Integration - Research Findings

**Date**: 29 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Comprehensive research findings for implementing OpenAPI specification on Platform layer
**Target Client**: DDH (Development Data Hub) via Azure API Management (APIM)

---

## 🎯 Executive Summary

The Platform layer provides a **REST API orchestration service** that sits above CoreMachine to translate external application requests into geospatial processing workflows. This research covers:

1. **Current Platform Layer Status** - What exists and what's broken
2. **OpenAPI Integration Requirements** - Minimum standards and APIM patterns
3. **DDH Integration Model** - Dataset/Resource/Version mandatory parameters
4. **Implementation Roadmap** - Hello World → STAC → ETL operations

---

## 📊 Current State Assessment (29 OCT 2025)

### ✅ What Exists

**Platform Layer Foundation** (Created 25-29 OCT 2025):
- `triggers/trigger_platform.py` - Platform request submission endpoint (POST /api/platform/submit)
- `triggers/trigger_platform_status.py` - Status monitoring endpoint (GET /api/platform/status/{request_id})
- Pydantic request/response models (`PlatformRequest`, `PlatformRecord`)
- Database schema (`platform.requests`, `platform.request_jobs` tables)
- Platform orchestrator that creates CoreMachine jobs

**Request Model Structure**:
```python
class PlatformRequest(BaseModel):
    dataset_id: str       # DDH dataset identifier
    resource_id: str      # DDH resource identifier
    version_id: str       # DDH version identifier
    data_type: DataType   # "raster", "vector", "pointcloud", etc.
    source_location: str  # Azure blob URL or path
    parameters: Dict[str, Any]  # Processing parameters
    client_id: str        # "ddh" or other client
```

**Response Model Structure**:
```python
{
    "success": true,
    "request_id": "abc123...",  # SHA256 hash (32 chars)
    "status": "pending",
    "jobs_created": ["job_id_1", "job_id_2"],
    "message": "Platform request submitted. 2 jobs created.",
    "monitor_url": "/api/platform/status/abc123..."
}
```

### ❌ What's Broken

**CRITICAL ISSUES** (Documented in `PLATFORM_LAYER_FIXES_TODO.md`):

1. **✅ FIXED (26 OCT)**: Import errors - Platform triggers load successfully now
2. **✅ FIXED (26 OCT)**: CoreMachine instantiation - Registries now passed correctly
3. **✅ FIXED (26 OCT)**: Service Bus repository pattern - Now uses proper architecture
4. **🟡 DEFERRED**: Schema initialization inefficiency (minor performance issue)

**TESTING STATUS**: Platform endpoints have **NOT been tested** with real requests yet. Code is ready but unvalidated.

### 🔍 Current API Endpoints

**Existing Platform Endpoints** (NOT OpenAPI compliant yet):
- `POST /api/platform/submit` - Submit processing request
- `GET /api/platform/status/{request_id}` - Get request status
- `GET /api/platform/status` - List all requests (with filters)

**Existing CoreMachine Endpoints** (Also not OpenAPI compliant):
- `POST /api/jobs/submit/{job_type}` - Direct job submission
- `GET /api/jobs/status/{job_id}` - Job status
- `GET /api/health` - System health check

---

## 🔧 OpenAPI Integration Requirements

### Minimum Requirements for OpenAPI Standards

**OpenAPI Specification Basics**:
1. **OpenAPI Document** - YAML/JSON file describing API (version 3.0.x or 3.1.x)
2. **Standard Components**:
   - `info`: API metadata (title, version, description)
   - `servers`: Base URLs
   - `paths`: Endpoints with operations (GET, POST, etc.)
   - `components/schemas`: Request/response models
   - `components/securitySchemes`: Authentication methods
3. **Request/Response Definitions** - All inputs/outputs documented with examples
4. **HTTP Status Codes** - Explicit documentation of success/error responses

**For Azure Functions + APIM**:
- OpenAPI spec can be **manually written** (no special extension required)
- APIM **imports** OpenAPI spec and creates API definition
- Function App exposes endpoints, APIM adds authentication/rate limiting/transformation

### APIM vs Function App Responsibilities

```
┌────────────────────────────────────────────────────────────┐
│                     Azure APIM                              │
│  ⚙️ Configuration Required in APIM Portal:                 │
│    • Import OpenAPI spec                                   │
│    • Configure products & subscriptions                    │
│    • Set rate limits & quotas                             │
│    • Define inbound/outbound policies                     │
│    • Configure authentication (OAuth, API keys)           │
│    • Set up CORS policies                                 │
│    • Configure backend URLs                               │
└────────────────────────┬───────────────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────────────┐
│              Azure Functions (Backend)                      │
│  📝 Implementation Required in Function App:                │
│    • Endpoints match OpenAPI paths                         │
│    • Request validation (Pydantic)                        │
│    • Response models match OpenAPI schemas                │
│    • Trust APIM headers (X-Client-Id, etc.)              │
│    • Return standardized error responses                  │
│    • Logging & Application Insights                      │
└────────────────────────────────────────────────────────────┘
```

**Critical Consistency Points**:
1. **Paths**: OpenAPI `paths` MUST match Function App HTTP routes
2. **Request Schemas**: OpenAPI schemas MUST match Pydantic models
3. **Response Schemas**: OpenAPI responses MUST match actual Function returns
4. **Status Codes**: OpenAPI status codes MUST match Function HTTP responses
5. **Parameter Names**: MUST be identical in OpenAPI and Pydantic (case-sensitive!)

**Example Consistency Issue**:
```yaml
# ❌ BAD - OpenAPI uses snake_case
openapi: 3.0.1
paths:
  /process:
    post:
      requestBody:
        content:
          application/json:
            schema:
              properties:
                data_set_id:  # ❌ Snake case
```

```python
# Function App uses camelCase (mismatch!)
class PlatformRequest(BaseModel):
    dataSetId: str  # ❌ Different casing
```

**✅ CORRECT - Both use same naming**:
```yaml
openapi: 3.0.1
# ...
    datasetId: string  # Matches Python
```

```python
class PlatformRequest(BaseModel):
    dataset_id: str  # Use snake_case, serialize to datasetId

    class Config:
        populate_by_name = True  # Accepts both dataset_id and datasetId
        json_schema_extra = {
            "properties": {
                "dataset_id": {"title": "datasetId"}  # OpenAPI name
            }
        }
```

---

## 🏗️ APIM Configuration Architecture

### What Must Be Configured in APIM Portal

**1. Import OpenAPI Specification**
- Upload/paste OpenAPI YAML/JSON
- APIM creates API definition automatically
- Endpoints become available in APIM

**2. Configure Products** (Access Control):
```
Product: "DDH-Platform-API"
  ├─ Subscriptions Required: Yes
  ├─ Approval Required: No (internal client)
  ├─ Rate Limit: 1000 calls/minute
  ├─ Quota: 100,000 calls/day
  └─ APIs Included:
      ├─ Platform Processing API v1
      └─ STAC Query API v1 (internal)
```

**3. Configure Policies** (XML in APIM Portal):

**Inbound Policy** (Request Processing):
```xml
<policies>
    <inbound>
        <!-- Validate subscription key -->
        <validate-subscription-key header-name="Ocp-Apim-Subscription-Key" />

        <!-- Extract client ID from subscription -->
        <set-header name="X-Client-Id" exists-action="override">
            <value>@(context.Subscription?.Name ?? "unknown")</value>
        </set-header>

        <!-- Add correlation ID -->
        <set-header name="X-Correlation-Id" exists-action="skip">
            <value>@(Guid.NewGuid().ToString())</value>
        </set-header>

        <!-- Rate limiting -->
        <rate-limit-by-key
            calls="1000"
            renewal-period="60"
            counter-key="@(context.Subscription?.Key)" />
    </inbound>

    <backend>
        <!-- Forward to Function App -->
        <base />
    </backend>

    <outbound>
        <!-- Add CORS for DDH -->
        <cors>
            <allowed-origins>
                <origin>https://ddh.application.com</origin>
            </allowed-origins>
        </cors>

        <!-- Transform Location header to full URL -->
        <set-header name="Location" exists-action="override">
            <value>@{
                var location = context.Response.Headers.GetValueOrDefault("Location","");
                return $"https://api.yourplatform.com/v1{location}";
            }</value>
        </set-header>
    </outbound>
</policies>
```

**4. Backend Configuration**:
- Backend URL: `https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net`
- Backend Type: Azure Function App
- Authentication: Managed Identity or Function Key

### What Stays in Function App

**Function App Responsibilities** (NO CHANGE to existing code pattern):
1. **HTTP Trigger Routes** - Already defined in `function_app.py`
2. **Request Validation** - Already using Pydantic models
3. **Business Logic** - Platform orchestrator creates CoreMachine jobs
4. **Response Models** - Already returning JSON with consistent structure
5. **Trust APIM Headers** - NEW: Read `X-Client-Id`, `X-Correlation-Id` from APIM

**NEW Code Pattern for APIM Integration**:
```python
# triggers/trigger_platform.py (ADDITION)

def extract_apim_headers(req: func.HttpRequest) -> Dict[str, str]:
    """Extract client information from APIM headers"""
    return {
        "client_id": req.headers.get("X-Client-Id", "unknown"),
        "correlation_id": req.headers.get("X-Correlation-Id", str(uuid.uuid4())),
        "subscription_name": req.headers.get("X-Subscription-Name", "unknown"),
        "rate_limit_remaining": req.headers.get("X-Rate-Limit-Remaining", "unknown")
    }

async def platform_request_submit(req: func.HttpRequest) -> func.HttpResponse:
    """Platform request submission endpoint"""

    # Extract APIM metadata (NEW)
    apim_info = extract_apim_headers(req)
    logger.info(f"Request from APIM client: {apim_info['client_id']}")

    # Existing validation and processing...
    req_body = req.get_json()
    platform_req = PlatformRequest(**req_body)

    # Add APIM info to metadata (NEW)
    platform_record.metadata.update({
        'apim_client_id': apim_info['client_id'],
        'apim_correlation_id': apim_info['correlation_id']
    })

    # Rest of existing code...
```

---

## 📋 DDH Integration Model

### DDH Three-Part Identifier (MANDATORY)

**DDH's Data Hierarchy**:
```
Dataset (e.g., "landsat-8-collection")
  ├─ Resource 1 (e.g., "LC08_L1TP_044034")
  │   ├─ Version 1.0 (original upload)
  │   └─ Version 1.1 (reprocessed)
  └─ Resource 2 (e.g., "LC08_L1TP_045035")
      └─ Version 1.0
```

**Required Parameters for ALL Platform Requests**:
```python
class PlatformRequest(BaseModel):
    # MANDATORY - DDH identifiers (already in current model ✅)
    dataset_id: str = Field(..., description="DDH dataset ID (e.g., 'landsat-8-collection')")
    resource_id: str = Field(..., description="DDH resource ID (e.g., 'LC08_L1TP_044034')")
    version_id: str = Field(..., description="DDH version ID (e.g., 'v1.0')")

    # MANDATORY - Processing instructions
    data_type: DataType = Field(..., description="Type of data: 'raster', 'vector', etc.")
    source_location: str = Field(..., description="Azure blob URL")

    # MANDATORY - Client identification
    client_id: str = Field(..., description="Always 'ddh' for DDH requests")

    # OPTIONAL - Processing customization
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Job-specific parameters")
```

**Request ID Generation** (Already implemented ✅):
```python
def generate_request_id(dataset_id: str, resource_id: str, version_id: str) -> str:
    """Generate deterministic request ID from DDH identifiers + timestamp"""
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    canonical = f"{dataset_id}:{resource_id}:{version_id}:{timestamp}"
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]  # 32-char hash
```

**Why Timestamp Included?**
- Allows DDH to reprocess same dataset/resource/version multiple times
- Each submission gets unique request_id
- Platform can track "this is the 3rd time they processed landsat-8/resource-1/v1.0"

### DDH Workflow Example

**DDH User Action**: Upload new raster file

**1. DDH Stores Metadata Internally**:
```python
# DDH's database
dataset = Dataset(id="aerial-imagery-2024")
resource = Resource(id="site-alpha", dataset=dataset)
version = Version(id="v1.0", resource=resource, file_path="aerial-alpha.tif")
```

**2. DDH Calls Platform API**:
```bash
curl -X POST https://api.platform.com/v1/process \
  -H "Ocp-Apim-Subscription-Key: ddh_subscription_key_abc123" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "aerial-imagery-2024",
    "resource_id": "site-alpha",
    "version_id": "v1.0",
    "data_type": "raster",
    "source_location": "https://storage.blob.core.windows.net/bronze/aerial-alpha.tif",
    "parameters": {"output_tier": "analysis"},
    "client_id": "ddh"
  }'
```

**3. Platform Returns Request ID**:
```json
{
  "success": true,
  "request_id": "a3f2c1b8e9d7f6a5",
  "status": "pending",
  "jobs_created": ["validate_raster_job_id", "process_raster_job_id"],
  "monitor_url": "https://api.platform.com/v1/status/a3f2c1b8e9d7f6a5"
}
```

**4. DDH Stores Platform Request ID**:
```python
# DDH updates version record
version.platform_request_id = "a3f2c1b8e9d7f6a5"
version.processing_status = "pending"
version.save()
```

**5. DDH Polls Status** (or receives webhook callback):
```bash
curl https://api.platform.com/v1/status/a3f2c1b8e9d7f6a5 \
  -H "Ocp-Apim-Subscription-Key: ddh_subscription_key_abc123"
```

**6. Platform Returns Completion**:
```json
{
  "request_id": "a3f2c1b8e9d7f6a5",
  "status": "completed",
  "jobs": [
    {"job_id": "...", "job_type": "validate_raster_job", "status": "completed"},
    {"job_id": "...", "job_type": "process_raster", "status": "completed"}
  ],
  "api_endpoints": {
    "tiles": "https://tiles.platform.com/{z}/{x}/{y}?dataset=aerial-imagery-2024&resource=site-alpha&version=v1.0",
    "stac": "https://stac.platform.com/collections/aerial-imagery-2024/items/site-alpha-v1.0",
    "download": "https://storage.blob.core.windows.net/silver-cogs/aerial-alpha-analysis.tif"
  },
  "data_characteristics": {
    "bbox": [-120.5, 38.0, -119.5, 39.0],
    "crs": "EPSG:4326",
    "file_size_mb": 45.2,
    "processing_time_seconds": 180
  }
}
```

**7. DDH Stores API Endpoints**:
```python
# DDH updates version with Platform-provided endpoints
version.api_endpoints = platform_response["api_endpoints"]
version.processing_status = "completed"
version.bbox = platform_response["data_characteristics"]["bbox"]
version.save()

# Now DDH users can discover and access the data via DDH's catalog UI
# Platform just provides the working endpoints
```

---

## 🚀 Implementation Roadmap

### Phase 1: Hello World + OpenAPI Foundation (Week 1)

**Goal**: Basic Platform endpoint with OpenAPI spec that APIM can import

**Tasks**:
1. **Create OpenAPI Specification** (`openapi/platform-api-v1.yaml`):
   ```yaml
   openapi: 3.0.1
   info:
     title: Platform Processing API
     version: v1.0.0
     description: Data processing platform for DDH and partners

   servers:
     - url: https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net
       description: Function App backend (direct access)
     - url: https://api.platform.com/v1
       description: APIM gateway (production)

   paths:
     /api/platform/submit:
       post:
         summary: Submit processing request
         operationId: submitProcessingRequest
         tags: [Platform]
         requestBody:
           required: true
           content:
             application/json:
               schema:
                 $ref: '#/components/schemas/PlatformRequest'
               examples:
                 helloWorld:
                   summary: Hello World test request
                   value:
                     dataset_id: "test-dataset"
                     resource_id: "test-resource"
                     version_id: "v1.0"
                     data_type: "raster"
                     source_location: "https://storage.blob.core.windows.net/bronze/test.tif"
                     parameters: {"test_mode": true}
                     client_id: "ddh"
         responses:
           '202':
             description: Request accepted for processing
             content:
               application/json:
                 schema:
                   $ref: '#/components/schemas/ProcessingResponse'
           '400':
             description: Invalid request
             content:
               application/json:
                 schema:
                   $ref: '#/components/schemas/ErrorResponse'

   components:
     schemas:
       PlatformRequest:
         type: object
         required:
           - dataset_id
           - resource_id
           - version_id
           - data_type
           - source_location
           - client_id
         properties:
           dataset_id:
             type: string
             description: DDH dataset identifier
             example: "landsat-8-collection"
           resource_id:
             type: string
             description: DDH resource identifier
             example: "LC08_L1TP_044034"
           version_id:
             type: string
             description: DDH version identifier
             example: "v1.0"
           data_type:
             type: string
             enum: [raster, vector, pointcloud, mesh_3d, tabular]
             description: Type of data to process
           source_location:
             type: string
             format: uri
             description: Azure blob URL or path
           parameters:
             type: object
             additionalProperties: true
             description: Job-specific processing parameters
           client_id:
             type: string
             description: Client application identifier
             example: "ddh"

       ProcessingResponse:
         type: object
         properties:
           success:
             type: boolean
           request_id:
             type: string
             description: Platform tracking ID (32-char hash)
           status:
             type: string
             enum: [pending, processing, completed, failed]
           jobs_created:
             type: array
             items:
               type: string
           message:
             type: string
           monitor_url:
             type: string
             format: uri

       ErrorResponse:
         type: object
         properties:
           success:
             type: boolean
             example: false
           error:
             type: string
           error_type:
             type: string

     securitySchemes:
       ApiKeyAuth:
         type: apiKey
         in: header
         name: Ocp-Apim-Subscription-Key

   security:
     - ApiKeyAuth: []
   ```

2. **Fix Platform Bugs** (from PLATFORM_LAYER_FIXES_TODO.md):
   - ✅ Already fixed: CoreMachine registries, Service Bus pattern
   - Test Platform endpoints work without crashes

3. **Test Hello World Flow**:
   ```bash
   # Direct Function App test (bypass APIM)
   curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/platform/submit \
     -H "Content-Type: application/json" \
     -d '{
       "dataset_id": "test-dataset",
       "resource_id": "test-resource",
       "version_id": "v1.0",
       "data_type": "raster",
       "source_location": "https://rmhazuregeo.blob.core.windows.net/rmhazuregeobronze/test.tif",
       "parameters": {"test_mode": true},
       "client_id": "ddh"
     }'
   ```

4. **Deploy OpenAPI Spec** (Documentation only, no code changes):
   - Create `/openapi/` folder in repo
   - Add `platform-api-v1.yaml`
   - Update `docs_claude/PLATFORM_OPENAPI_SPEC.md` with usage instructions

**Deliverables**:
- ✅ OpenAPI spec file that validates with Swagger Editor
- ✅ Platform endpoint responds successfully to test requests
- ✅ Documentation: "How to import OpenAPI spec into APIM"

**Time Estimate**: 2-4 hours

---

### Phase 2: STAC Query Operations (Week 2)

**Goal**: Add STAC query endpoints with OpenAPI documentation

**STAC Query Patterns**:

**1. Collection Queries** (Existing in CoreMachine):
```python
# Already working: GET /api/stac/collections/{collection_id}
# Needs: OpenAPI documentation + APIM exposure
```

**2. Item Queries** (Existing in CoreMachine):
```python
# Already working: GET /api/stac/collections/{collection_id}/items
# Needs: OpenAPI documentation + APIM exposure
```

**3. Search Endpoint** (NEW - needs implementation):
```python
# POST /api/stac/search
# Body: {"bbox": [...], "datetime": "2024-01-01/2024-12-31", "collections": ["..."]}
```

**OpenAPI Additions**:
```yaml
paths:
  /api/stac/collections:
    get:
      summary: List STAC collections
      operationId: listSTACCollections
      tags: [STAC]
      responses:
        '200':
          description: List of collections
          content:
            application/json:
              schema:
                type: object
                properties:
                  collections:
                    type: array
                    items:
                      $ref: '#/components/schemas/STACCollection'

  /api/stac/collections/{collectionId}/items:
    get:
      summary: Get items in collection
      operationId: getSTACItems
      tags: [STAC]
      parameters:
        - name: collectionId
          in: path
          required: true
          schema:
            type: string
        - name: bbox
          in: query
          schema:
            type: string
          description: Bounding box (minx,miny,maxx,maxy)
        - name: datetime
          in: query
          schema:
            type: string
          description: Datetime range (RFC3339)
        - name: limit
          in: query
          schema:
            type: integer
            default: 10
      responses:
        '200':
          description: Feature collection
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/GeoJSONFeatureCollection'

  /api/stac/search:
    post:
      summary: Search STAC items
      operationId: searchSTACItems
      tags: [STAC]
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/STACSearchRequest'
      responses:
        '200':
          description: Matching items
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/GeoJSONFeatureCollection'

components:
  schemas:
    STACSearchRequest:
      type: object
      properties:
        bbox:
          type: array
          items:
            type: number
          minItems: 4
          maxItems: 4
          description: Bounding box [minx, miny, maxx, maxy]
        datetime:
          type: string
          description: RFC3339 datetime or range
        collections:
          type: array
          items:
            type: string
        limit:
          type: integer
          default: 10
        filter:
          type: object
          description: CQL2 filter (future)
```

**Implementation Tasks**:
1. **Document existing STAC endpoints** in OpenAPI spec
2. **Create STAC search endpoint** (if not exists)
3. **Add APIM policies** for STAC query rate limiting
4. **Test with DDH queries**:
   ```bash
   # Get all rasters for a dataset
   curl -X POST https://api.platform.com/v1/stac/search \
     -H "Ocp-Apim-Subscription-Key: ddh_key" \
     -d '{
       "collections": ["aerial-imagery-2024"],
       "bbox": [-120, 38, -119, 39]
     }'
   ```

**Deliverables**:
- ✅ STAC endpoints documented in OpenAPI spec
- ✅ STAC search working via APIM
- ✅ DDH can query processed data

**Time Estimate**: 3-5 hours

---

### Phase 3: ETL Operations (Week 3+)

**Goal**: Full raster/vector processing workflows via Platform API

**ETL Operations to Expose**:

**1. Raster Processing**:
```yaml
paths:
  /api/platform/submit:
    post:
      # (Already exists from Phase 1)
      requestBody:
        examples:
          rasterProcessing:
            summary: Process raster to COG
            value:
              dataset_id: "aerial-survey-2024"
              resource_id: "site-bravo"
              version_id: "v2.0"
              data_type: "raster"
              source_location: "https://storage/bronze/site-bravo.tif"
              parameters:
                output_tier: "analysis"
                target_crs: "EPSG:4326"
              client_id: "ddh"
```

**2. Vector Processing**:
```yaml
          vectorProcessing:
            summary: Ingest vector to PostGIS
            value:
              dataset_id: "boundary-data-2024"
              resource_id: "district-boundaries"
              version_id: "v1.0"
              data_type: "vector"
              source_location: "https://storage/bronze/boundaries.geojson"
              parameters:
                target_crs: "EPSG:4326"
                table_name: "district_boundaries"
              client_id: "ddh"
```

**3. Collection Processing**:
```yaml
          collectionProcessing:
            summary: Process multiple rasters as collection
            value:
              dataset_id: "satellite-tiles-2024"
              resource_id: "landsat-scene-123"
              version_id: "v1.0"
              data_type: "raster"
              source_location: "https://storage/bronze/landsat/*_R{row}C{col}.tif"
              parameters:
                create_mosaicjson: true
                output_tier: "visualization"
              client_id: "ddh"
```

**Implementation Tasks**:
1. **Update OpenAPI examples** with real-world ETL scenarios
2. **Test each data_type** flows through Platform → CoreMachine
3. **Document expected processing times** in OpenAPI descriptions
4. **Add status polling guidance** for long-running jobs

**Deliverables**:
- ✅ Complete OpenAPI spec with all ETL operations
- ✅ DDH integration guide with code examples
- ✅ Error handling documentation

**Time Estimate**: 5-8 hours

---

## 📝 OpenAPI Best Practices for This Project

### 1. Use Existing Pydantic Models as Source of Truth

**✅ GOOD Pattern**:
```python
# 1. Define Pydantic model (source of truth)
class PlatformRequest(BaseModel):
    dataset_id: str = Field(..., description="DDH dataset ID")
    # ... rest of fields

# 2. Generate OpenAPI schema from Pydantic
# (Can use pydantic.json_schema() to export)
openapi_schema = PlatformRequest.model_json_schema()

# 3. Paste into OpenAPI YAML (manual for now, can automate later)
```

**❌ BAD Pattern**:
- Writing OpenAPI spec first, then changing Pydantic models to match
- Maintaining two separate definitions that drift apart

### 2. Include Realistic Examples

```yaml
components:
  schemas:
    PlatformRequest:
      # ... schema definition
      example:  # ✅ Add example at schema level
        dataset_id: "aerial-imagery-2024"
        resource_id: "site-alpha"
        version_id: "v1.0"
        data_type: "raster"
        source_location: "https://rmhazuregeo.blob.core.windows.net/bronze/site-alpha.tif"
        parameters:
          output_tier: "analysis"
          target_crs: "EPSG:4326"
        client_id: "ddh"
```

### 3. Document Error Responses

```yaml
responses:
  '400':
    description: Invalid request parameters
    content:
      application/json:
        schema:
          $ref: '#/components/schemas/ErrorResponse'
        examples:
          missingDatasetId:
            summary: Missing required field
            value:
              success: false
              error: "Field 'dataset_id' is required"
              error_type: "ValidationError"
          invalidDataType:
            summary: Invalid enum value
            value:
              success: false
              error: "data_type must be one of: raster, vector, pointcloud"
              error_type: "ValidationError"
```

### 4. Version in URL Path

```yaml
servers:
  - url: https://api.platform.com/v1  # ✅ Version in path
    description: Production API

# NOT:
servers:
  - url: https://api.platform.com  # ❌ No versioning
```

### 5. Use Tags for Organization

```yaml
tags:
  - name: Platform
    description: Processing request management
  - name: STAC
    description: STAC catalog queries
  - name: Status
    description: Job status monitoring

paths:
  /api/platform/submit:
    post:
      tags: [Platform]  # ✅ Groups operations in Swagger UI
```

---

## 🎯 Success Criteria

### Phase 1 Success (Hello World):
- [ ] OpenAPI spec validates in Swagger Editor (https://editor.swagger.io)
- [ ] Can import spec into APIM without errors
- [ ] Direct Function App call works: POST /api/platform/submit
- [ ] APIM gateway call works with subscription key
- [ ] Response matches OpenAPI schema exactly

### Phase 2 Success (STAC):
- [ ] STAC endpoints documented in OpenAPI
- [ ] Can query STAC collections via APIM
- [ ] DDH can retrieve processed data metadata
- [ ] Rate limiting works (1000 calls/min for DDH)

### Phase 3 Success (ETL):
- [ ] Raster processing works end-to-end via Platform API
- [ ] Vector processing works end-to-end via Platform API
- [ ] Status polling shows real-time progress
- [ ] API endpoints returned to DDH are accessible

---

## 📚 Reference Links

### OpenAPI Resources:
- **OpenAPI 3.0 Specification**: https://swagger.io/specification/
- **Swagger Editor**: https://editor.swagger.io (validate specs)
- **OpenAPI Generator**: https://openapi-generator.tech (client SDKs)

### Azure APIM Resources:
- **Import OpenAPI**: https://learn.microsoft.com/en-us/azure/api-management/import-api-from-oas
- **APIM Policies**: https://learn.microsoft.com/en-us/azure/api-management/api-management-policies
- **Products & Subscriptions**: https://learn.microsoft.com/en-us/azure/api-management/api-management-howto-add-products

### Pydantic Resources:
- **JSON Schema Export**: https://docs.pydantic.dev/latest/concepts/json_schema/
- **Field Descriptions**: https://docs.pydantic.dev/latest/concepts/fields/

---

## 🚦 Next Actions (Exit Plan Mode)

**Immediate**:
1. Review findings with Robert
2. Confirm DDH integration model (dataset_id/resource_id/version_id)
3. Confirm APIM availability and access

**Phase 1 Implementation** (Hello World):
1. Create `/openapi/platform-api-v1.yaml`
2. Test Platform endpoint works (fix any remaining bugs)
3. Document APIM import process
4. Test end-to-end: DDH → APIM → Function App → CoreMachine

**Questions for Robert**:
1. Do you have APIM instance already provisioned?
2. What's the APIM base URL (e.g., https://api.platform.com)?
3. Should I create OpenAPI spec now or wait for approval?
4. Is DDH ready to integrate or is this exploratory?

---

**Document Status**: ✅ RESEARCH COMPLETE
**Ready for Implementation**: Yes (pending Robert's approval)
**Estimated Total Effort**: 10-17 hours across 3 phases
