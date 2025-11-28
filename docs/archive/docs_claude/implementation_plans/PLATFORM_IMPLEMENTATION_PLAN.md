# Platform Service Implementation Plan

**Date**: 25 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Step-by-step implementation plan for DDH Platform Service

## Overview

Build a platform service layer on top of existing CoreMachine infrastructure to serve DDH and future applications. Leverage existing components while adding client-facing abstraction layer.

## Current Assets to Leverage

### What We Already Have:
1. **CoreMachine**: Orchestrates Job→Stage→Task workflows ✅
2. **Job Library**: 10+ working job types (vector, raster, STAC) ✅
3. **Service Bus**: Queue processing infrastructure ✅
4. **PostgreSQL**: Database with jobs/tasks tables ✅
5. **STAC Integration**: pgSTAC already installed ✅
6. **Processing Logic**: COG creation, vector ingestion, tiling ✅

### What We Need to Build:
1. **Client-facing API layer** (accepts DDH requests)
2. **Request tracking system** (platform_requests table)
3. **Job orchestration mapping** (request → multiple jobs)
4. **STAC response formatting** (for DDH)
5. **Webhook system** (notify DDH on completion)
6. **API key management** (for restricted STAC access)

## Implementation Phases

## Phase 1: MVP Foundation (Week 1-2)
**Goal**: Basic request→process→respond flow for DDH

### 1.1 Database Schema (Day 1-2)

```sql
-- New schema for platform layer
CREATE SCHEMA platform;

-- Platform requests from clients
CREATE TABLE platform.requests (
    request_id VARCHAR(32) PRIMARY KEY,        -- SHA256 prefix
    client_id VARCHAR(50) NOT NULL,            -- 'ddh_v1'
    client_request_id VARCHAR(255),            -- DDH's reference

    -- Identity (for DDH)
    dataset_id VARCHAR(255),
    resource_id VARCHAR(255),
    version_id VARCHAR(50),

    -- Processing
    request_type VARCHAR(50) NOT NULL,         -- 'vector', 'raster'
    source_path TEXT NOT NULL,                 -- Blob storage path
    processing_config JSONB DEFAULT '{}',

    -- Status
    status VARCHAR(20) DEFAULT 'pending',      -- pending|processing|completed|failed
    progress_percent INT DEFAULT 0,
    status_message TEXT,

    -- Jobs tracking
    job_ids JSONB DEFAULT '[]',               -- CoreMachine job IDs
    current_job_index INT DEFAULT 0,

    -- Results
    endpoints JSONB,                          -- API endpoints when ready
    stac_metadata JSONB,                      -- STAC response for DDH
    processing_metadata JSONB DEFAULT '{}',

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,

    -- Callback
    callback_url TEXT,
    callback_status VARCHAR(20),              -- pending|sent|failed

    CONSTRAINT unique_request UNIQUE(dataset_id, resource_id, version_id)
);

-- Link existing jobs to platform requests
ALTER TABLE app.jobs
ADD COLUMN platform_request_id VARCHAR(32),
ADD CONSTRAINT fk_platform_request
    FOREIGN KEY (platform_request_id)
    REFERENCES platform.requests(request_id);

-- API keys for STAC access (Phase 2)
CREATE TABLE platform.api_keys (
    key_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id VARCHAR(50) NOT NULL,
    api_key_hash VARCHAR(64) NOT NULL,        -- SHA256 of actual key
    access_level VARCHAR(20) NOT NULL,        -- internal|trusted|admin
    allowed_endpoints JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    rotated_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT true
);
```

### 1.2 Platform Request Models (Day 2)

```python
# platform/models.py
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from enum import Enum

class PlatformRequestStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class DDHRequest(BaseModel):
    """Request from DDH to process data"""
    dataset_id: str
    resource_id: str
    version_id: str
    request_type: str  # 'vector', 'raster', 'collection'
    source_path: str
    processing_config: Dict[str, Any] = {}
    callback_url: Optional[str] = None

class PlatformResponse(BaseModel):
    """Response to DDH with tracking info"""
    request_id: str
    status: str
    status_url: str
    estimated_completion: Optional[str] = None

class PlatformStatusResponse(BaseModel):
    """Status check response"""
    request_id: str
    status: str
    progress_percent: int
    message: Optional[str]

    # When completed
    endpoints: Optional[Dict[str, str]] = None
    stac_metadata: Optional[Dict[str, Any]] = None
```

### 1.3 Request Router (Day 3-4)

```python
# platform/router.py
from typing import Dict, Any
import hashlib
import json

class PlatformRouter:
    """Routes platform requests to CoreMachine jobs"""

    # Map request types to job sequences
    JOB_MAPPINGS = {
        "vector": ["ingest_vector", "stac_catalog_vectors"],
        "raster": ["validate_raster", "process_raster"],
        "collection": ["process_raster_collection", "create_mosaic_json"]
    }

    def __init__(self, core_machine, platform_repo):
        self.core_machine = core_machine
        self.platform_repo = platform_repo

    def process_request(self, request: DDHRequest) -> PlatformResponse:
        """Main entry point for DDH requests"""

        # Generate unique request ID
        request_id = self._generate_request_id(request)

        # Check for existing (idempotency)
        existing = self.platform_repo.get_request(request_id)
        if existing:
            return PlatformResponse(
                request_id=existing.request_id,
                status=existing.status,
                status_url=f"/platform/status/{existing.request_id}"
            )

        # Create platform request record
        platform_request = self.platform_repo.create_request({
            "request_id": request_id,
            "client_id": "ddh_v1",
            "dataset_id": request.dataset_id,
            "resource_id": request.resource_id,
            "version_id": request.version_id,
            "request_type": request.request_type,
            "source_path": request.source_path,
            "processing_config": request.processing_config,
            "callback_url": request.callback_url,
            "status": "pending"
        })

        # Get job sequence for this request type
        job_types = self.JOB_MAPPINGS.get(request.request_type, [])

        # Submit first job
        if job_types:
            self._submit_next_job(platform_request, job_types[0])

        return PlatformResponse(
            request_id=request_id,
            status="accepted",
            status_url=f"/platform/status/{request_id}",
            estimated_completion="2025-10-25T12:00:00Z"
        )

    def _submit_next_job(self, platform_request, job_type: str):
        """Submit job to CoreMachine"""

        # Build job parameters based on type
        job_params = self._build_job_params(platform_request, job_type)

        # Add platform tracking
        job_params["_platform_request_id"] = platform_request.request_id

        # Submit via existing job submission (reuse existing code!)
        from triggers.submit_job import submit_job_trigger
        job_result = submit_job_trigger.submit_job(job_type, job_params)

        # Track job ID
        platform_request.job_ids.append(job_result["job_id"])
        platform_request.status = "processing"
        self.platform_repo.update_request(platform_request)
```

### 1.4 HTTP Endpoints (Day 4-5)

```python
# Add to function_app.py

# Platform endpoints for DDH
platform_router = PlatformRouter(core_machine, platform_repo)

@app.route(route="platform/submit", methods=["POST"])
def platform_submit(req: func.HttpRequest) -> func.HttpResponse:
    """
    Accept processing request from DDH.
    Returns 202 Accepted with tracking info.
    """
    try:
        # Parse DDH request
        request = DDHRequest.model_validate_json(req.get_body())

        # Process through platform router
        response = platform_router.process_request(request)

        # Return 202 Accepted
        return func.HttpResponse(
            response.model_dump_json(),
            status_code=202,
            mimetype="application/json",
            headers={
                "Location": response.status_url
            }
        )
    except Exception as e:
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=400,
            mimetype="application/json"
        )

@app.route(route="platform/status/{request_id}", methods=["GET"])
def platform_status(req: func.HttpRequest) -> func.HttpResponse:
    """
    Check status of platform request.
    DDH polls this endpoint.
    """
    request_id = req.route_params.get('request_id')

    # Get request from database
    platform_request = platform_repo.get_request(request_id)

    if not platform_request:
        return func.HttpResponse(status_code=404)

    # Build status response
    response = PlatformStatusResponse(
        request_id=platform_request.request_id,
        status=platform_request.status,
        progress_percent=platform_request.progress_percent,
        message=platform_request.status_message
    )

    # Add results if completed
    if platform_request.status == "completed":
        response.endpoints = platform_request.endpoints
        response.stac_metadata = platform_request.stac_metadata

    return func.HttpResponse(
        response.model_dump_json(),
        mimetype="application/json"
    )
```

### 1.5 Job Completion Handler (Day 5-6)

```python
# platform/completion.py

class PlatformCompletionHandler:
    """Handles job completion and advances platform requests"""

    def handle_job_completion(self, job_id: str, job_result: Dict):
        """Called when a CoreMachine job completes"""

        # Find platform request
        platform_request = platform_repo.get_by_job_id(job_id)
        if not platform_request:
            return  # Not a platform job

        # Check if more jobs to run
        job_types = JOB_MAPPINGS[platform_request.request_type]
        current_index = platform_request.job_ids.index(job_id)

        if current_index < len(job_types) - 1:
            # Submit next job
            next_job_type = job_types[current_index + 1]
            platform_router._submit_next_job(platform_request, next_job_type)
        else:
            # All jobs complete
            self._complete_platform_request(platform_request)

    def _complete_platform_request(self, platform_request):
        """Finalize platform request"""

        # Generate endpoints based on type
        endpoints = self._generate_endpoints(platform_request)

        # Get STAC metadata from last job
        stac_metadata = self._extract_stac_metadata(platform_request)

        # Update request
        platform_request.status = "completed"
        platform_request.endpoints = endpoints
        platform_request.stac_metadata = stac_metadata
        platform_request.completed_at = datetime.utcnow()
        platform_repo.update_request(platform_request)

        # Send webhook to DDH
        if platform_request.callback_url:
            self._send_webhook(platform_request)
```

## Phase 2: STAC Integration (Week 2-3)
**Goal**: Return STAC metadata to DDH, implement restricted API

### 2.1 STAC Response Builder (Day 7-8)

```python
# platform/stac_builder.py

class STACResponseBuilder:
    """Builds STAC responses for DDH"""

    def build_stac_response(self, platform_request, processing_results):
        """Create STAC metadata for DDH"""

        if platform_request.request_type == "vector":
            return self._build_vector_stac(platform_request, processing_results)
        elif platform_request.request_type == "raster":
            return self._build_raster_stac(platform_request, processing_results)

    def _build_vector_stac(self, request, results):
        """Build STAC Item for vector data"""
        return {
            "type": "Feature",
            "id": f"{request.dataset_id}_{request.resource_id}_{request.version_id}",
            "collection": "ddh_vectors",
            "geometry": results.get("bbox_geom"),
            "properties": {
                "datetime": datetime.utcnow().isoformat(),
                "ddh:dataset_id": request.dataset_id,
                "ddh:resource_id": request.resource_id,
                "ddh:version_id": request.version_id,
                "vector:feature_count": results.get("feature_count"),
                "proj:epsg": results.get("crs", 4326)
            },
            "assets": {
                "data": {
                    "href": f"/platform/data/{request.request_id}/download",
                    "type": "application/geopackage+sqlite3"
                }
            }
        }
```

### 2.2 Restricted STAC API (Day 9-10)

```python
# platform/stac_api.py

@app.route(route="platform/stac/search", methods=["POST"])
def platform_stac_search(req: func.HttpRequest) -> func.HttpResponse:
    """
    STAC search - RESTRICTED to DDH backend
    """
    # Check API key
    api_key = req.headers.get("X-Platform-API-Key")
    if not validate_api_key(api_key, "ddh_v1"):
        return func.HttpResponse(status_code=401)

    # Parse search request
    search = req.get_json()

    # Query pgSTAC (reuse existing infrastructure)
    results = pgstac_client.search(
        collections=["ddh_vectors", "ddh_rasters"],
        datetime=search.get("datetime"),
        bbox=search.get("bbox"),
        filter=search.get("filter")
    )

    return func.HttpResponse(
        json.dumps(results),
        mimetype="application/geo+json"
    )
```

## Phase 3: Production Hardening (Week 3-4)
**Goal**: Webhooks, monitoring, error handling

### 3.1 Webhook System (Day 11-12)

```python
# platform/webhooks.py

class WebhookManager:
    """Manages webhook delivery to DDH"""

    def send_completion_webhook(self, platform_request):
        """Send completion notification to DDH"""

        payload = {
            "request_id": platform_request.request_id,
            "dataset_id": platform_request.dataset_id,
            "resource_id": platform_request.resource_id,
            "version_id": platform_request.version_id,
            "status": "completed",
            "endpoints": platform_request.endpoints,
            "stac_metadata": platform_request.stac_metadata,
            "processing_time_seconds": (
                platform_request.completed_at - platform_request.created_at
            ).total_seconds()
        }

        # Sign payload for security
        signature = self._sign_payload(payload)

        # Send with retries
        response = requests.post(
            platform_request.callback_url,
            json=payload,
            headers={
                "X-Platform-Signature": signature,
                "Content-Type": "application/json"
            },
            timeout=30
        )

        # Track webhook status
        platform_request.callback_status = "sent" if response.ok else "failed"
        platform_repo.update_request(platform_request)
```

### 3.2 Monitoring & Health (Day 13-14)

```python
# Add platform health to existing health check

def _check_platform_health(self) -> Dict[str, Any]:
    """Platform service health check"""

    # Check pending requests
    pending_count = platform_repo.count_by_status("pending")
    processing_count = platform_repo.count_by_status("processing")

    # Get average processing time
    avg_time = platform_repo.get_average_processing_time()

    # Check webhook delivery rate
    webhook_success_rate = platform_repo.get_webhook_success_rate()

    return {
        "component": "platform_service",
        "status": "healthy",
        "metrics": {
            "pending_requests": pending_count,
            "processing_requests": processing_count,
            "average_processing_seconds": avg_time,
            "webhook_success_rate": webhook_success_rate
        },
        "ddh_integration": {
            "api_key_configured": True,
            "callback_url_configured": True,
            "last_successful_webhook": platform_repo.get_last_webhook_time()
        }
    }
```

## Phase 4: Advanced Features (Week 4+)
**Goal**: Optimizations and additional features

### 4.1 Batch Processing
- Handle multiple versions efficiently
- Detect incremental changes
- Reuse previous processing when possible

### 4.2 Caching Layer
- Cache STAC responses
- CDN integration for tiles
- Pre-generate common formats

### 4.3 Multi-Client Support
- Add client configuration system
- Per-client rate limiting
- Usage analytics

## Testing Strategy

### Week 1 Tests (MVP)
1. Submit vector dataset → Get tracking ID
2. Poll status → See progress updates
3. Completion → Receive endpoints

### Week 2 Tests (STAC)
1. STAC metadata in responses
2. STAC search with API key
3. Unauthorized access blocked

### Week 3 Tests (Production)
1. Webhook delivery to DDH
2. Error handling and retries
3. Performance under load

### Integration Tests with DDH
1. End-to-end: Upload → Process → Access
2. STAC metadata transformation
3. Webhook handling
4. Status polling patterns

## Risk Mitigation

### Technical Risks
1. **CoreMachine compatibility**: Platform layer is additive, doesn't modify core
2. **Database migrations**: New schema, doesn't touch existing tables
3. **Performance**: Reuse existing job processing, just add orchestration

### Integration Risks
1. **DDH API changes**: Use versioned endpoints (ddh_v1)
2. **STAC format**: Follow official STAC spec 1.0.0
3. **Webhook failures**: Implement retry with exponential backoff

## Success Criteria

### Phase 1 Success (MVP)
- [ ] DDH can submit processing requests
- [ ] Requests get processed by existing jobs
- [ ] DDH can poll for status
- [ ] Completion returns endpoints

### Phase 2 Success (STAC)
- [ ] STAC metadata in responses
- [ ] DDH can query STAC API with key
- [ ] Public cannot access STAC API

### Phase 3 Success (Production)
- [ ] Webhooks delivered reliably
- [ ] 99% success rate on processing
- [ ] Average processing < 5 minutes

## Resource Requirements

### Development Team
- 1-2 developers for 4 weeks
- Existing CoreMachine knowledge helpful
- STAC experience beneficial

### Infrastructure
- No new infrastructure needed
- Reuse existing Azure Functions
- Reuse existing PostgreSQL
- Reuse existing Service Bus

### External Dependencies
- DDH team for integration testing
- API key exchange with DDH
- Webhook endpoint from DDH

This phased approach lets us deliver value quickly (Week 1 MVP) while building toward a robust platform service that can serve DDH and future clients!