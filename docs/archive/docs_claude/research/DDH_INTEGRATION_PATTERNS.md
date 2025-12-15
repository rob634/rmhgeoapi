# DDH and Multi-Application Access Patterns

**Date**: 25 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Define access patterns for DDH (primary) and future applications

## DDH (Development Data Hub) - Primary Client

DDH is the main data catalog application that:
- Manages user-submitted datasets with rich metadata
- Organizes data in Dataset → Resource → Version hierarchy
- Handles all user-facing metadata, permissions, discovery
- Needs our platform to process data into accessible APIs

## Access Pattern Types

Different applications have different needs. We should design for these patterns:

### Pattern 1: Catalog Pattern (DDH)
**Characteristics:**
- Heavy metadata management
- User-driven uploads
- Version control important
- Browse/search/discover workflows
- Multiple data formats

**Access Needs:**
- Async processing (202 pattern)
- Status polling
- Webhook callbacks
- Persistent endpoints
- Multiple API types per dataset

### Pattern 2: Real-time Analytics Pattern
**Characteristics:**
- Need fast responses
- Often temporary data
- Compute-heavy operations
- Results more important than persistence

**Access Needs:**
- Synchronous processing for small data
- Streaming results
- Temporary endpoints OK
- WebSocket updates
- Priority queue access

### Pattern 3: Batch Processing Pattern
**Characteristics:**
- Large volume submissions
- Scheduled processing
- System-to-system integration
- Automated workflows

**Access Needs:**
- Bulk submission API
- Batch status tracking
- SLA guarantees
- Rate limiting
- Programmatic access only

### Pattern 4: Embedded/Widget Pattern
**Characteristics:**
- Lightweight clients
- Limited authentication
- Public or semi-public data
- Simple visualization needs

**Access Needs:**
- CORS support
- Anonymous access tiers
- Cached/CDN-friendly
- Simple REST only
- GeoJSON/MVT formats

## DDH-Specific Integration Design

### DDH Request Flow

```python
class DDHProcessingRequest(BaseModel):
    """
    DDH-specific request format that maps to their data model.
    """
    # DDH Identity
    dataset_id: str          # DDH's dataset ID
    resource_id: str         # DDH's resource ID
    version_id: str          # DDH's version ID

    # DDH Metadata (we store but don't process)
    ddh_metadata: Dict[str, Any] = {}
    # {
    #   "title": "2020 Census Blocks",
    #   "owner": "user@example.com",
    #   "tags": ["census", "demographics"],
    #   "visibility": "public"
    # }

    # Processing Instructions
    data_type: str           # Detected by DDH
    source_file: str         # Path in DDH's storage

    # DDH Processing Preferences
    processing_profile: str = "standard"  # "standard", "performance", "archival"

    # DDH expects these endpoints
    required_endpoints: List[str] = ["ogc_features", "bulk_download"]

    # DDH callback
    ddh_callback_url: str
    ddh_callback_token: str  # Auth token for callback

class DDHProcessingResponse(BaseModel):
    """
    DDH-specific response format.
    """
    # Tracking
    request_id: str          # Our tracking ID
    ddh_reference: str       # Their reference (dataset/resource/version)

    # Status
    status: str
    status_url: str
    status_webhook: bool = True  # DDH always wants webhooks

    # Results
    endpoints: DDHEndpoints
    processing_metadata: DDHMetadata

class DDHEndpoints(BaseModel):
    """
    Endpoint structure that DDH expects.
    """
    # Standard endpoints DDH can display
    ogc_features: Optional[str]     # /datasets/{id}/features
    ogc_tiles: Optional[str]         # /datasets/{id}/tiles/{z}/{x}/{y}
    bulk_download: Optional[str]     # /datasets/{id}/download
    stac_item: Optional[str]         # /datasets/{id}/stac

    # Advanced endpoints
    analytics_api: Optional[str]     # /datasets/{id}/analytics
    streaming: Optional[str]         # /datasets/{id}/stream

    # Metadata about endpoints
    authentication_required: bool = False
    rate_limits: Dict[str, int] = {}
    cache_ttl: int = 3600

class DDHMetadata(BaseModel):
    """
    Processing metadata that DDH displays to users.
    """
    processing_time_seconds: float
    data_characteristics: Dict[str, Any]
    # {
    #   "format": "GeoPackage",
    #   "crs": "EPSG:4326",
    #   "feature_count": 50000,
    #   "geometry_type": "Polygon",
    #   "bbox": [-180, -90, 180, 90],
    #   "file_size_mb": 125.3
    # }
    processing_notes: List[str] = []
    quality_indicators: Dict[str, Any] = {}
```

### DDH Webhook Contract

```python
class DDHWebhookPayload(BaseModel):
    """
    What we send to DDH when processing completes.
    """
    # Identity
    dataset_id: str
    resource_id: str
    version_id: str
    request_id: str

    # Status
    status: str  # "completed", "failed", "partial"

    # Results (if completed)
    endpoints: Optional[DDHEndpoints]
    metadata: Optional[DDHMetadata]

    # Error (if failed)
    error: Optional[Dict[str, Any]]

    # Signature for verification
    signature: str  # HMAC-SHA256 of payload

# DDH webhook handler example
@app.route("/ddh/webhook", methods=["POST"])
def handle_ddh_webhook():
    payload = DDHWebhookPayload.parse_raw(request.body)

    # Verify signature
    if not verify_signature(payload.signature, request.headers["X-Platform-Signature"]):
        return 401

    # Update DDH database
    ddh_version = get_version(payload.dataset_id, payload.resource_id, payload.version_id)
    ddh_version.processing_status = payload.status
    ddh_version.api_endpoints = payload.endpoints
    ddh_version.platform_metadata = payload.metadata
    ddh_version.save()

    # Notify DDH users if needed
    if payload.status == "completed":
        notify_users(f"Dataset {payload.dataset_id} is now available")

    return 200
```

## Platform Configuration for Different Access Patterns

### Multi-Tenant Configuration

```python
class ClientConfiguration(BaseModel):
    """
    Per-client configuration in our platform.
    """
    client_id: str
    client_name: str
    access_pattern: str  # "catalog", "analytics", "batch", "embedded"

    # Authentication
    auth_method: str  # "api_key", "oauth2", "webhook_token"
    auth_config: Dict[str, Any]

    # Processing
    priority: int = 5  # 1-10, higher = faster processing
    max_concurrent_requests: int = 10
    max_data_size_gb: float = 10.0
    allowed_data_types: List[str] = ["vector", "raster"]

    # Endpoints
    endpoint_prefix: str  # e.g., "/ddh", "/analytics"
    endpoint_lifetime_days: Optional[int] = None  # None = permanent
    allowed_endpoint_types: List[str]

    # Callbacks
    webhook_enabled: bool = True
    webhook_url: Optional[str]
    webhook_retry_policy: Dict[str, Any] = {}

    # Rate limiting
    rate_limit_per_minute: int = 60
    rate_limit_per_day: int = 1000

    # SLA
    sla_processing_time_seconds: Optional[int]
    sla_availability_percent: float = 99.0

# Platform client registry
REGISTERED_CLIENTS = {
    "ddh_v1": ClientConfiguration(
        client_id="ddh_v1",
        client_name="Development Data Hub",
        access_pattern="catalog",
        auth_method="webhook_token",
        auth_config={"token_header": "X-DDH-Token"},
        priority=7,
        max_concurrent_requests=50,
        max_data_size_gb=100.0,
        endpoint_prefix="/ddh",
        endpoint_lifetime_days=None,  # Permanent
        allowed_endpoint_types=["ogc_features", "ogc_tiles", "bulk_download", "stac"],
        webhook_url="https://ddh.application.com/api/webhooks/platform",
        rate_limit_per_minute=100,
        rate_limit_per_day=10000
    ),

    "analytics_platform": ClientConfiguration(
        client_id="analytics_platform",
        client_name="Analytics Engine",
        access_pattern="analytics",
        auth_method="api_key",
        priority=9,  # Higher priority for real-time
        max_concurrent_requests=20,
        max_data_size_gb=5.0,
        endpoint_prefix="/analytics",
        endpoint_lifetime_days=7,  # Temporary
        allowed_endpoint_types=["streaming", "websocket"],
        webhook_enabled=False,
        rate_limit_per_minute=200
    ),

    "public_viewer": ClientConfiguration(
        client_id="public_viewer",
        client_name="Public Map Viewer",
        access_pattern="embedded",
        auth_method="none",
        priority=3,  # Lower priority
        max_concurrent_requests=100,
        max_data_size_gb=1.0,
        endpoint_prefix="/public",
        allowed_endpoint_types=["ogc_tiles", "geojson"],
        webhook_enabled=False,
        rate_limit_per_minute=30
    )
}
```

### Request Router by Pattern

```python
class PatternBasedRouter:
    """
    Routes requests based on client's access pattern.
    """

    def route_request(self, client_id: str, request: ProcessingRequest):
        client_config = REGISTERED_CLIENTS.get(client_id)
        if not client_config:
            raise ValueError(f"Unregistered client: {client_id}")

        # Route based on access pattern
        if client_config.access_pattern == "catalog":
            return self.handle_catalog_pattern(request, client_config)
        elif client_config.access_pattern == "analytics":
            return self.handle_analytics_pattern(request, client_config)
        elif client_config.access_pattern == "batch":
            return self.handle_batch_pattern(request, client_config)
        elif client_config.access_pattern == "embedded":
            return self.handle_embedded_pattern(request, client_config)

    def handle_catalog_pattern(self, request: ProcessingRequest, config: ClientConfiguration):
        """
        Catalog pattern (DDH): Async, persistent, multiple endpoints
        """
        # Always async
        job_id = self.submit_async_job(request, priority=config.priority)

        # Create persistent endpoints
        endpoints = self.create_persistent_endpoints(
            request,
            prefix=config.endpoint_prefix,
            types=config.allowed_endpoint_types
        )

        # Setup webhook
        if config.webhook_enabled:
            self.register_webhook(job_id, config.webhook_url)

        return ProcessingResponse(
            status="accepted",
            request_id=job_id,
            status_url=f"/status/{job_id}",
            estimated_completion=self.estimate_time(request)
        )

    def handle_analytics_pattern(self, request: ProcessingRequest, config: ClientConfiguration):
        """
        Analytics pattern: Try sync for small data, streaming for large
        """
        data_size = self.estimate_data_size(request)

        if data_size < 10_000_000:  # 10MB
            # Synchronous processing
            result = self.process_sync(request, timeout=30)
            return ProcessingResponse(
                status="completed",
                data=result,
                endpoint=self.create_temporary_endpoint(result, ttl=3600)
            )
        else:
            # Streaming response
            stream_id = self.create_stream(request)
            return ProcessingResponse(
                status="streaming",
                stream_url=f"/stream/{stream_id}",
                websocket_url=f"ws://platform/stream/{stream_id}"
            )

    def handle_embedded_pattern(self, request: ProcessingRequest, config: ClientConfiguration):
        """
        Embedded pattern: Cached, CDN-friendly, simple formats
        """
        # Check cache first
        cached = self.get_cached_result(request)
        if cached:
            return ProcessingResponse(
                status="completed",
                endpoint=cached.endpoint,
                cache_hit=True
            )

        # Process with caching
        job_id = self.submit_async_job(request, cache=True, cache_ttl=86400)

        # Create CDN-friendly endpoints
        endpoints = self.create_cdn_endpoints(
            request,
            formats=["geojson", "mvt"],  # Web-friendly formats
            cors_enabled=True
        )

        return ProcessingResponse(
            status="processing",
            request_id=job_id,
            endpoints=endpoints,
            cache_ttl=86400
        )
```

## DDH-Specific Optimizations

### 1. Batch Version Processing
When DDH uploads multiple versions, process efficiently:

```python
class DDHBatchProcessor:
    """
    Handle multiple versions of same dataset/resource efficiently.
    """

    def process_version_batch(self, dataset_id: str, resource_id: str, versions: List[str]):
        # Detect what changed between versions
        changes = self.detect_changes(versions)

        if changes.type == "incremental":
            # Only process deltas
            return self.process_incremental(versions)
        elif changes.type == "schema_change":
            # Full reprocessing needed
            return self.process_full(versions)
        else:
            # Copy endpoints from previous version
            return self.copy_endpoints(versions[-2], versions[-1])
```

### 2. DDH Metadata Passthrough
Preserve DDH's metadata without processing:

```python
def process_ddh_request(request: DDHProcessingRequest):
    # Store DDH metadata for return in callback
    metadata_store[request.request_id] = request.ddh_metadata

    # Process data (ignoring DDH metadata)
    result = process_data(request.source_file, request.data_type)

    # Return DDH metadata unchanged in callback
    webhook_payload = {
        "endpoints": result.endpoints,
        "ddh_metadata": metadata_store[request.request_id],  # Unchanged
        "platform_metadata": result.metadata  # Our processing metadata
    }
```

### 3. DDH-Specific Health Endpoints

```python
@app.route("/ddh/health", methods=["GET"])
def ddh_health():
    """
    DDH-specific health check with their expected format.
    """
    return {
        "platform_status": "healthy",
        "ddh_integration": {
            "webhook_url": "configured",
            "last_successful_callback": "2025-10-25T10:00:00Z",
            "pending_requests": 5,
            "average_processing_time": 45.3
        },
        "available_endpoints": [
            "ogc_features",
            "ogc_tiles",
            "bulk_download",
            "stac"
        ]
    }
```

## Benefits of Multi-Pattern Design

### For DDH
- Optimized for catalog workflows
- Persistent endpoints for discovered data
- Rich metadata preservation
- Webhook integration for async updates

### For Future Applications
- Each app gets appropriate processing pattern
- No forced catalog structure
- Flexible authentication methods
- Performance tiers based on use case

### For Platform
- Resource optimization by pattern
- Better SLA management
- Predictable scaling
- Clear client segmentation

This design ensures DDH gets exactly what it needs while keeping the platform flexible for future applications!