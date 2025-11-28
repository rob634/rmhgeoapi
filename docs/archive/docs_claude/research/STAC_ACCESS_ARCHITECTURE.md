# STAC Access Architecture - Internal vs External

**Date**: 25 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Define STAC access patterns for DDH (internal) vs future trusted applications

## Key Architectural Decision

**STAC serves two distinct purposes:**
1. **Internal Metadata Exchange** (DDH) - STAC as data transfer format
2. **Trusted API Access** (Future) - STAC API for authorized applications

**Critical**: End users NEVER directly access STAC - they use DDH's metadata layer.

## Access Tiers

```
┌─────────────────────────────────────────────────────┐
│                    END USERS                        │
│         (Access DDH UI - Never see STAC)            │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────┐
│              DDH (Data Discovery Hub)               │
│                                                      │
│  • Manages ALL user-facing metadata                 │
│  • Provides search/discovery UI                     │
│  • Controls access permissions                      │
│  • Receives STAC metadata from platform             │
│  • Transforms STAC to user-friendly format          │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼ (STAC as response format)
┌─────────────────────────────────────────────────────┐
│              PLATFORM (Our Service)                 │
│                                                      │
│  ┌────────────────────────────────────────────┐    │
│  │         STAC Metadata Layer                │    │
│  │                                            │    │
│  │  • Generated during processing             │    │
│  │  • Returned to DDH in responses           │    │
│  │  • Stored in pgSTAC database              │    │
│  │  • NOT publicly accessible                │    │
│  └────────────────────────────────────────────┘    │
│                                                      │
│  ┌────────────────────────────────────────────┐    │
│  │     STAC API (Restricted Access)          │    │
│  │                                            │    │
│  │  • /stac/search - Authorized apps only    │    │
│  │  • /stac/collections - Internal use       │    │
│  │  • /stac/items - Requires API key         │    │
│  └────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────┘
                     │
                     ▼ (Future - Trusted Apps Only)
┌─────────────────────────────────────────────────────┐
│            TRUSTED APPLICATIONS                     │
│                                                      │
│  • GIS Systems (with API keys)                      │
│  • Analytics Platforms (authenticated)              │
│  • Partner Organizations (whitelisted)              │
└─────────────────────────────────────────────────────┘
```

## STAC Response Formats for DDH

### 1. STAC in Processing Response (Immediate)

```python
class DDHProcessingResponse(BaseModel):
    """
    Enhanced response that includes STAC metadata for DDH.
    """
    # Standard tracking
    request_id: str
    status: str

    # API Endpoints (for data access)
    endpoints: DDHEndpoints

    # STAC Metadata (for DDH's catalog)
    stac_metadata: Optional[STACResponse] = None

class STACResponse(BaseModel):
    """
    STAC metadata returned to DDH - NOT for end users.
    DDH uses this to populate their own metadata system.
    """
    stac_type: str  # "Feature" or "Collection"

    # STAC Item (for individual datasets)
    stac_item: Optional[Dict[str, Any]]  # Full STAC Item JSON

    # STAC Collection (for grouped datasets)
    stac_collection: Optional[Dict[str, Any]]  # Full STAC Collection JSON

    # Extracted key fields for DDH convenience
    spatial_extent: Dict[str, Any]  # Bbox, geometry
    temporal_extent: Optional[Dict[str, Any]]  # Time range
    properties: Dict[str, Any]  # All STAC properties
    assets: Dict[str, Any]  # Links to actual data

    # Internal STAC API reference (NOT for end users)
    _internal_stac_url: Optional[str]  # For DDH backend use only

# Example response to DDH
{
    "request_id": "proc_abc123",
    "status": "completed",
    "endpoints": {
        "ogc_features": "https://platform/ddh/dataset/resource/version/features",
        "tiles": "https://platform/ddh/dataset/resource/version/tiles/{z}/{x}/{y}"
    },
    "stac_metadata": {
        "stac_type": "Feature",
        "stac_item": {
            "type": "Feature",
            "id": "dataset_resource_version",
            "collection": "ddh_datasets",
            "geometry": {...},
            "properties": {
                "datetime": "2025-10-25T10:00:00Z",
                "eo:cloud_cover": 5,
                "proj:epsg": 4326,
                "ddh:dataset_id": "census_2020",
                "ddh:resource_id": "blocks",
                "ddh:version_id": "v1.2"
            },
            "assets": {
                "data": {
                    "href": "https://platform/ddh/dataset/resource/version/download",
                    "type": "application/geopackage+sqlite3"
                },
                "thumbnail": {
                    "href": "https://platform/ddh/dataset/resource/version/preview.png",
                    "type": "image/png"
                }
            }
        },
        "spatial_extent": {
            "bbox": [[-180, -90, 180, 90]]
        },
        "_internal_stac_url": "https://platform/internal/stac/items/abc123"
    }
}
```

### 2. DDH Uses STAC to Populate Their Metadata

```python
# How DDH processes our STAC response
def handle_platform_stac_response(stac_response: STACResponse):
    """
    DDH transforms STAC metadata into their user-facing format.
    """
    # Extract spatial info for DDH's map interface
    ddh_spatial = {
        "bounding_box": stac_response.spatial_extent["bbox"][0],
        "geometry_type": detect_geometry_type(stac_response.stac_item),
        "coordinate_system": stac_response.properties.get("proj:epsg", "unknown")
    }

    # Extract temporal info if available
    ddh_temporal = None
    if stac_response.temporal_extent:
        ddh_temporal = {
            "start_date": stac_response.temporal_extent.get("interval", [[None, None]])[0][0],
            "end_date": stac_response.temporal_extent.get("interval", [[None, None]])[0][1]
        }

    # Create DDH's user-facing metadata (no STAC terminology)
    user_metadata = {
        "spatial_coverage": ddh_spatial,
        "temporal_coverage": ddh_temporal,
        "data_quality": extract_quality_metrics(stac_response.properties),
        "processing_info": {
            "processed_date": stac_response.properties.get("datetime"),
            "processing_version": stac_response.properties.get("processing:version")
        }
    }

    # Store in DDH's database (users never see "STAC")
    save_to_ddh_catalog(user_metadata)
```

## Restricted STAC API Access

### Access Control Levels

```python
class STACAccessLevel(Enum):
    """
    Different access levels for STAC API.
    """
    NONE = "none"              # No access (default for public)
    INTERNAL = "internal"      # Platform-to-DDH only
    TRUSTED = "trusted"        # Authorized applications
    ADMIN = "admin"           # Full access for debugging

class STACAccessControl:
    """
    Controls who can access STAC endpoints.
    """

    # Whitelist of trusted applications
    TRUSTED_APPS = {
        "ddh_backend": {
            "level": STACAccessLevel.INTERNAL,
            "api_key": "ddh_secret_key_xyz",
            "allowed_endpoints": ["/stac/search", "/stac/items"],
            "ip_whitelist": ["10.0.0.5", "10.0.0.6"]
        },
        "analytics_platform": {
            "level": STACAccessLevel.TRUSTED,
            "api_key": "analytics_key_abc",
            "allowed_endpoints": ["/stac/search"],
            "rate_limit": 100  # requests per minute
        },
        "qgis_enterprise": {
            "level": STACAccessLevel.TRUSTED,
            "api_key": "qgis_key_def",
            "allowed_endpoints": ["/stac/", "/stac/search", "/stac/collections"],
            "rate_limit": 50
        }
    }

    def check_access(self, request: Request) -> bool:
        """
        Verify if request has access to STAC API.
        """
        # Extract API key
        api_key = request.headers.get("X-STAC-API-Key")
        if not api_key:
            return False

        # Find app config
        app_config = None
        for app_id, config in self.TRUSTED_APPS.items():
            if config["api_key"] == api_key:
                app_config = config
                break

        if not app_config:
            return False

        # Check endpoint access
        if request.path not in app_config.get("allowed_endpoints", []):
            return False

        # Check IP whitelist if configured
        if "ip_whitelist" in app_config:
            if request.remote_addr not in app_config["ip_whitelist"]:
                return False

        # Check rate limit
        if not self.check_rate_limit(api_key, app_config.get("rate_limit")):
            return False

        return True
```

### Protected STAC Endpoints

```python
@app.route(route="stac", methods=["GET"])
def stac_root(req: func.HttpRequest) -> func.HttpResponse:
    """
    STAC API root - RESTRICTED ACCESS.
    """
    # Check authorization
    if not stac_access_control.check_access(req):
        return func.HttpResponse(
            json.dumps({"error": "Unauthorized"}),
            status_code=401
        )

    # Return STAC catalog root
    return get_stac_catalog()

@app.route(route="stac/search", methods=["GET", "POST"])
def stac_search(req: func.HttpRequest) -> func.HttpResponse:
    """
    STAC search endpoint - RESTRICTED ACCESS.

    DDH backend uses this to query processed datasets.
    NOT exposed to end users - they use DDH's search.
    """
    # Check authorization
    if not stac_access_control.check_access(req):
        return func.HttpResponse(
            json.dumps({"error": "Unauthorized"}),
            status_code=401
        )

    # Log access for audit
    log_stac_access(req.headers.get("X-STAC-API-Key"), "search", req.params)

    # Perform STAC search
    results = search_stac_catalog(req.params)

    # Filter results based on access level
    filtered_results = filter_by_access_level(results, req.headers.get("X-STAC-API-Key"))

    return func.HttpResponse(
        json.dumps(filtered_results),
        mimetype="application/geo+json"
    )

@app.route(route="stac/collections/{collection_id}/items/{item_id}")
def stac_item(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get specific STAC item - RESTRICTED ACCESS.
    """
    # Check authorization
    if not stac_access_control.check_access(req):
        return func.HttpResponse(
            json.dumps({"error": "Unauthorized"}),
            status_code=401
        )

    collection_id = req.route_params.get('collection_id')
    item_id = req.route_params.get('item_id')

    # Get STAC item
    item = get_stac_item(collection_id, item_id)

    # Remove internal fields based on access level
    item = sanitize_stac_response(item, req.headers.get("X-STAC-API-Key"))

    return func.HttpResponse(
        json.dumps(item),
        mimetype="application/geo+json"
    )
```

## Implementation Phases

### Phase 1: STAC as Response Format (Immediate Need)
1. Generate STAC metadata during processing
2. Include in DDH responses
3. No public API access yet

### Phase 2: Internal STAC API (DDH Backend)
1. Implement restricted STAC endpoints
2. API key authentication for DDH
3. Audit logging of access

### Phase 3: Trusted Application Access (Future)
1. Whitelist trusted applications
2. Implement rate limiting
3. Different access levels per app
4. Usage analytics

### Phase 4: STAC Federation (Long-term)
1. Connect to other STAC catalogs
2. Federated search capabilities
3. Cross-platform data discovery

## Security Considerations

### API Key Management
```python
class STACAPIKeyManager:
    """
    Manages API keys for STAC access.
    """

    def rotate_key(self, app_id: str) -> str:
        """
        Rotate API key for security.
        """
        old_key = self.get_current_key(app_id)
        new_key = self.generate_secure_key()

        # Grace period for transition
        self.keys[app_id] = {
            "current": new_key,
            "previous": old_key,
            "rotation_date": datetime.utcnow(),
            "grace_period_hours": 24
        }

        # Notify application owner
        self.notify_key_rotation(app_id, new_key)

        return new_key

    def validate_key(self, key: str) -> bool:
        """
        Validate API key including grace period check.
        """
        for app_id, key_info in self.keys.items():
            if key == key_info["current"]:
                return True

            # Check previous key during grace period
            if key == key_info.get("previous"):
                grace_end = key_info["rotation_date"] + timedelta(hours=key_info["grace_period_hours"])
                if datetime.utcnow() < grace_end:
                    return True

        return False
```

### Audit Logging
```python
def log_stac_access(api_key: str, endpoint: str, params: dict):
    """
    Log all STAC API access for security audit.
    """
    audit_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "api_key_hash": hashlib.sha256(api_key.encode()).hexdigest()[:8],
        "endpoint": endpoint,
        "params": params,
        "ip_address": request.remote_addr,
        "user_agent": request.user_agent
    }

    # Store in audit log
    audit_logger.info(json.dumps(audit_entry))

    # Alert on suspicious patterns
    if detect_suspicious_access(api_key, endpoint):
        security_alert(f"Suspicious STAC access from {api_key[:8]}...")
```

## Benefits of This Architecture

### For DDH
1. **Rich Metadata**: Gets full STAC spec compliance
2. **No Lock-in**: Can transform STAC to any format
3. **Future-proof**: STAC is industry standard
4. **Hidden Complexity**: End users never see STAC

### For Platform
1. **Single Source**: STAC as universal metadata format
2. **Standards Compliance**: Following OGC/STAC specs
3. **Controlled Access**: No public STAC exposure
4. **Future Flexibility**: Can open API to trusted apps later

### For Future Applications
1. **Optional Access**: Can request STAC API access
2. **Standard Format**: Use existing STAC clients
3. **Rich Queries**: Spatial/temporal/property searches
4. **Interoperability**: Connect to other STAC systems

This ensures STAC serves its purpose as a metadata exchange format while maintaining DDH's control over user-facing metadata!