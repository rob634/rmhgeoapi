# STAC Metadata Extraction Strategy (DRY Analysis)

**Date**: 5 OCT 2025
**Author**: Robert and Geospatial Claude Legion

## 🎯 Core Question

**What metadata needs to be extracted for STAC Items, and how much can we delegate to existing libraries (DRY principle)?**

## 📋 STAC Item Required Fields (Specification)

### Mandatory Fields
```python
{
    # GeoJSON core fields
    "id": str,                    # Unique identifier
    "type": "Feature",            # Must be "Feature"
    "geometry": {...},            # GeoJSON geometry (footprint)
    "bbox": [xmin, ymin, xmax, ymax],  # Bounding box (required if geometry != null)

    # STAC-specific fields
    "properties": {
        "datetime": str           # ISO 8601 UTC timestamp (REQUIRED)
        # ... additional metadata
    },
    "assets": {...},              # Files/resources
    "links": [...],               # Related resources
    "stac_version": "1.0.0",
    "collection": str             # Collection ID (if part of collection)
}
```

## 🔧 What Libraries Extract Automatically

### rio-stac: `create_stac_item()`

**Automatically Extracted from GeoTIFF:**
```python
from rio_stac import stac
import rasterio

with rasterio.open("file.tif") as dataset:
    item_dict = stac.create_stac_item(
        dataset,
        id="auto-generated-id",           # Optional - defaults to filename
        collection="collection-id",       # Optional - we provide
        input_datetime=datetime.now(),    # Optional - defaults to NOW or ACQUISITIONDATETIME metadata
        with_proj=True,                   # Add projection extension
        with_raster=True,                 # Add raster extension
        with_eo=True                      # Add EO extension
    )
```

**What rio-stac Extracts Automatically:**
✅ **Geometry** - Footprint polygon from dataset bounds
✅ **BBox** - Bounding box from dataset bounds
✅ **Projection** - EPSG code, WKT2, or PROJJSON from dataset CRS
✅ **Raster Properties** - Band count, data types, nodata values
✅ **Band Statistics** - Min/max/mean/stddev (if `with_raster=True`)
✅ **Media Type** - `image/tiff; application=geotiff; profile=cloud-optimized`
✅ **Asset Definition** - Creates default asset with href

**What We Must Provide:**
❌ **Item ID** - Defaults to filename, but we should use semantic IDs
❌ **Collection ID** - Must specify which collection
❌ **Datetime** - Defaults to NOW, but we should use blob last_modified or custom
❌ **Additional Properties** - Custom metadata (Azure container, tier, etc.)
❌ **Links** - Collection links, self links, etc.

### stac-pydantic: Validation & Type Safety

**What stac-pydantic Provides:**
✅ **Automatic Schema Validation** - Validates against STAC 1.0.0 spec
✅ **Type Safety** - Pydantic models with full type hints
✅ **Extension Validation** - Validates extension properties against JSON schemas
✅ **Serialization** - Converts to/from JSON with proper formatting

```python
from stac_pydantic import Item

# Validate dict from rio-stac
item = Item(**item_dict)  # Raises ValidationError if invalid

# Access with type safety
item.id              # str
item.geometry        # dict
item.properties      # dict
item.assets          # dict[str, Asset]
```

## 📊 Current vs STAC Metadata Comparison

### What We Already Extract (container_list.py)

```python
# From analyze_single_blob()
{
    "blob_name": str,              # ✅ Can use for Item ID
    "blob_path": str,              # ✅ Can use for Asset href
    "container_name": str,         # ✅ Use for collection determination
    "size_bytes": int,             # ✅ Already have
    "size_mb": float,              # ✅ Already have
    "file_extension": str,         # ✅ Filter .tif files
    "content_type": str,           # ✅ Already have
    "last_modified": str,          # ✅ Use for datetime property
    "etag": str,                   # ✅ Already have
    "metadata": dict               # ✅ Azure blob metadata
}
```

### What STAC Needs (Additional)

```python
# From rio-stac extraction
{
    "geometry": {...},             # ❌ Need rasterio
    "bbox": [xmin, ymin, xmax, ymax],  # ❌ Need rasterio
    "projection": {                # ❌ Need rasterio
        "epsg": int,
        "wkt2": str,
        "projjson": {...}
    },
    "raster": {                    # ❌ Need rasterio (optional but valuable)
        "bands": [...],
        "statistics": {...}
    },
    "eo": {                        # ❌ Need specialized extraction (optional)
        "cloud_cover": float
    }
}
```

## ✅ DRY Strategy: Leverage Libraries Maximally

### Recommended Approach

**DON'T re-implement what rio-stac already does:**
- ❌ Don't manually calculate geometry from bounds
- ❌ Don't manually parse CRS to get EPSG codes
- ❌ Don't manually read band statistics
- ❌ Don't manually construct asset definitions

**DO use rio-stac for heavy lifting:**
- ✅ Let rio-stac extract geometry, bbox, projection, raster metadata
- ✅ Let rio-stac construct proper STAC Item structure
- ✅ Let rio-stac handle extension properties

**DO supplement with our existing metadata:**
- ✅ Use our `last_modified` for `datetime` property
- ✅ Use our `container_name` to determine collection
- ✅ Use our `blob_path` to generate Azure Storage URLs
- ✅ Add custom Azure-specific properties

## 🏗️ Proposed Implementation Pattern

### Service: `services/service_stac_metadata.py`

```python
from typing import Dict, Any, Optional
from datetime import datetime
from stac_pydantic import Item, Asset
from rio_stac import stac
import rasterio
from rasterio.session import AWSSession
from infrastructure.blob import BlobRepository


class StacMetadataService:
    """
    Extract STAC metadata from blobs using rio-stac + our existing metadata.

    Strategy: DRY - Leverage libraries for heavy lifting, supplement with our data.
    """

    def __init__(self):
        self.blob_repo = BlobRepository.instance()

    def extract_item_from_blob(
        self,
        container: str,
        blob_name: str,
        collection_id: str,
        existing_metadata: Optional[Dict[str, Any]] = None
    ) -> Item:
        """
        Extract STAC Item from blob using rio-stac.

        Args:
            container: Azure container name
            blob_name: Blob path within container
            collection_id: STAC collection ID
            existing_metadata: Optional metadata from analyze_single_blob()

        Returns:
            Validated stac-pydantic Item

        Strategy:
            1. Generate blob URL with SAS token
            2. Let rio-stac extract geometry, bbox, projection, raster metadata
            3. Supplement with our existing metadata (datetime, Azure properties)
            4. Validate with stac-pydantic
        """
        # Generate blob URL with SAS token for rasterio access
        blob_url = self.blob_repo.generate_sas_url(
            container=container,
            blob_path=blob_name,
            hours=1
        )

        # Determine datetime (prefer existing metadata, fallback to NOW)
        if existing_metadata and existing_metadata.get('last_modified'):
            item_datetime = datetime.fromisoformat(existing_metadata['last_modified'])
        else:
            # rio-stac will use NOW if not provided
            item_datetime = None

        # Generate semantic item ID
        item_id = self._generate_item_id(container, blob_name)

        # LET RIO-STAC DO THE HEAVY LIFTING
        with rasterio.open(blob_url) as dataset:
            item_dict = stac.create_stac_item(
                dataset,
                id=item_id,
                collection=collection_id,
                input_datetime=item_datetime,
                asset_name="data",
                asset_roles=["data"],
                asset_media_type="image/tiff; application=geotiff; profile=cloud-optimized",
                with_proj=True,     # Extract projection extension
                with_raster=True,   # Extract raster extension
                with_eo=False       # EO requires specialized extraction
            )

        # SUPPLEMENT with Azure-specific properties
        item_dict['properties']['azure:container'] = container
        item_dict['properties']['azure:blob_path'] = blob_name
        item_dict['properties']['azure:tier'] = self._determine_tier(container)

        if existing_metadata:
            item_dict['properties']['azure:size_mb'] = existing_metadata.get('size_mb')
            item_dict['properties']['azure:etag'] = existing_metadata.get('etag')
            item_dict['properties']['azure:content_type'] = existing_metadata.get('content_type')

        # VALIDATE with stac-pydantic
        item = Item(**item_dict)

        return item

    def _generate_item_id(self, container: str, blob_name: str) -> str:
        """Generate semantic STAC Item ID."""
        # Example: bronze-rmhazuregeobronze-path-to-file-tif
        tier = self._determine_tier(container)
        safe_name = blob_name.replace('/', '-').replace('.', '-')
        return f"{tier}-{safe_name}"

    def _determine_tier(self, container: str) -> str:
        """Determine tier from container name."""
        container_lower = container.lower()
        if 'bronze' in container_lower:
            return 'bronze'
        elif 'silver' in container_lower:
            return 'silver'
        elif 'gold' in container_lower:
            return 'gold'
        return 'unknown'
```

## 🔄 Integration with Existing Workflow

### Two-Stage Pattern Enhancement

**Current Pattern:**
```
Stage 1: list_container_blobs()  → Returns blob names
Stage 2: analyze_single_blob()   → Returns blob metadata (size, modified, etc.)
```

**Enhanced with STAC:**
```
Stage 1: list_container_blobs()       → Returns blob names
Stage 2: extract_stac_item()          → Uses rio-stac + our metadata → Insert into PgSTAC
         ├─ analyze_single_blob()     → Get Azure metadata (size, modified)
         └─ rio-stac extraction       → Get spatial metadata (geometry, bbox, projection)
```

### Code Integration

```python
def extract_and_insert_stac_item(params: dict) -> dict[str, Any]:
    """
    Stage 2: Extract STAC metadata and insert into PgSTAC.

    Replaces: analyze_single_blob()
    Enhances: Now extracts full STAC metadata + inserts into PgSTAC
    """
    try:
        container = params["container_name"]
        blob_name = params["blob_name"]
        collection_id = params.get("collection_id", f"bronze-{container}")

        # 1. Get basic Azure metadata (REUSE existing code)
        blob_metadata = analyze_single_blob(params)
        if not blob_metadata['success']:
            return blob_metadata

        # 2. Extract STAC Item using rio-stac (DRY - don't reimplement)
        stac_service = StacMetadataService()
        item = stac_service.extract_item_from_blob(
            container=container,
            blob_name=blob_name,
            collection_id=collection_id,
            existing_metadata=blob_metadata['result']
        )

        # 3. Insert into PgSTAC
        stac_infra = StacInfrastructure()
        insert_result = stac_infra.insert_item(item, collection_id)

        return {
            'success': True,
            'result': {
                'item_id': item.id,
                'collection': collection_id,
                'blob_metadata': blob_metadata['result'],
                'stac_item': item.model_dump(mode='json'),
                'pgstac_result': insert_result
            }
        }

    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__
        }
```

## 📊 Metadata Sources Summary

| Field | Source | Method |
|-------|--------|--------|
| **id** | Generated | `_generate_item_id()` |
| **geometry** | rio-stac | `create_stac_item()` |
| **bbox** | rio-stac | `create_stac_item()` |
| **datetime** | Our metadata | `blob.last_modified` |
| **projection** | rio-stac | `with_proj=True` |
| **raster** | rio-stac | `with_raster=True` |
| **assets** | rio-stac | `create_stac_item()` |
| **azure:container** | Our data | Custom property |
| **azure:tier** | Our logic | `_determine_tier()` |
| **azure:size_mb** | Our metadata | `blob.size_mb` |
| **links** | Generated | Collection links |

## ✅ Benefits of This Approach

### 1. DRY Principle
- ✅ Don't reimplement geometry calculation (rio-stac does it)
- ✅ Don't reimplement projection parsing (rio-stac does it)
- ✅ Don't reimplement band statistics (rio-stac does it)
- ✅ Don't reimplement STAC schema validation (stac-pydantic does it)

### 2. Leverage Existing Code
- ✅ Reuse `analyze_single_blob()` for Azure metadata
- ✅ Reuse `BlobRepository.generate_sas_url()` for access
- ✅ Reuse existing filter logic from container operations

### 3. Library Strengths
- ✅ rio-stac: Spatial metadata extraction (geometry, projection)
- ✅ stac-pydantic: Validation & type safety
- ✅ Our code: Azure-specific metadata & workflow orchestration

### 4. Maintainability
- ✅ Libraries handle STAC spec updates
- ✅ Libraries handle edge cases (malformed rasters, projections)
- ✅ Our code focuses on business logic (tier determination, workflow)

## 🎯 Implementation Checklist

- [ ] Add `stac-pydantic>=3.4.0` to requirements.txt (already have `rio-stac>=0.9.0`)
- [ ] Create `services/service_stac_metadata.py` with `StacMetadataService`
- [ ] Add `generate_sas_url()` to `BlobRepository` (for rasterio access)
- [ ] Add `insert_item()` to `infrastructure/stac.py`
- [ ] Create `extract_and_insert_stac_item()` function
- [ ] Create HTTP trigger for STAC extraction workflow
- [ ] Test with Bronze container
- [ ] Verify Items appear in PgSTAC

## 🔑 Key Takeaway

**Maximize DRY by delegating to libraries:**

- **rio-stac** → Geometry, BBox, Projection, Raster metadata
- **stac-pydantic** → Validation, Type safety, Serialization
- **Our code** → Azure metadata, Workflow orchestration, Custom properties

**Result**: Minimal custom code, maximum reliability, easy maintenance.
