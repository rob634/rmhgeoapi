# STAC-Pydantic Integration Analysis

**Date**: 5 OCT 2025
**Author**: Robert and Geospatial Claude Legion

## 🎯 Executive Summary

**stac-pydantic** is a PERFECT fit for our Pydantic-authoritarian architecture. It provides strongly-typed Pydantic v2 models for STAC Items, Collections, Catalogs, and Assets with automatic validation.

## ✅ Compatibility Check

| Component | Our Version | stac-pydantic Requirement | Status |
|-----------|-------------|---------------------------|--------|
| **Pydantic** | `>=2.0.0` | `^2.4` | ✅ Compatible |
| **Python** | 3.11+ | `>=3.8` | ✅ Compatible |
| **STAC Spec** | 1.0.0 | 1.0.0 | ✅ Compatible |

## 📦 Library Comparison

### stac-pydantic vs pystac

| Feature | **stac-pydantic** | **pystac** |
|---------|-------------------|------------|
| **Purpose** | Validation & typing | General STAC manipulation |
| **Type Safety** | ✅ Full Pydantic models | ❌ Dict-based |
| **Validation** | ✅ Automatic schema validation | Manual validation |
| **FastAPI Integration** | ✅ Native request/response models | ❌ Requires conversion |
| **Extensions** | ✅ JSON schema validation | ✅ Built-in extension classes |
| **Our Use Case** | **PERFECT** - Matches our philosophy | Useful for STAC manipulation |

**Decision**: Use **stac-pydantic** as primary library for metadata extraction and validation. Keep **pystac** for advanced STAC operations if needed.

## 🏗️ Available Models

### Core STAC Models
```python
from stac_pydantic import Item, Collection, Catalog, Asset

# Item - Individual geospatial asset
item = Item(
    id="sentinel-2-l2a-2025-10-05",
    type="Feature",
    stac_version="1.0.0",
    geometry={"type": "Polygon", "coordinates": [...]},
    bbox=[-180, -90, 180, 90],
    properties={
        "datetime": "2025-10-05T00:00:00Z",
        "eo:cloud_cover": 15.2
    },
    assets={
        "visual": Asset(
            href="https://example.com/visual.tif",
            type="image/tiff; application=geotiff; profile=cloud-optimized",
            roles=["visual"]
        )
    },
    links=[...]
)

# Collection - Group of related items
collection = Collection(
    id="bronze-rmhazuregeobronze",
    type="Collection",
    stac_version="1.0.0",
    description="Raw geospatial data from Azure Storage",
    license="proprietary",
    extent={
        "spatial": {"bbox": [[-180, -90, 180, 90]]},
        "temporal": {"interval": [[None, None]]}
    },
    summaries={
        "azure:container": ["rmhazuregeobronze"],
        "azure:tier": ["bronze"]
    }
)

# Asset - Individual file within an item
asset = Asset(
    href="https://rmhazuregeobronze.blob.core.windows.net/container/file.tif",
    type="image/tiff; application=geotiff; profile=cloud-optimized",
    title="Cloud Optimized GeoTIFF",
    roles=["data"],
    eo_bands=[...]
)
```

### Extension Support
```python
from stac_pydantic import Item
from stac_pydantic.extensions import eo, projection

# Item with EO (Electro-Optical) extension
item = Item(
    id="sentinel-2-item",
    stac_extensions=[
        "https://stac-extensions.github.io/eo/v1.0.0/schema.json"
    ],
    properties={
        "datetime": "2025-10-05T00:00:00Z",
        "eo:cloud_cover": 15.2,
        "eo:snow_cover": 0.0
    },
    ...
)

# Automatic validation of extension properties
model.validate_extensions()  # Validates against JSON schemas
```

## 🎯 Integration Strategy for Our Architecture

### Phase 1: Add stac-pydantic Dependency
```bash
# Add to requirements.txt
stac-pydantic>=3.4.0
```

### Phase 2: Create STAC Metadata Extraction Service

**File**: `services/service_stac_metadata.py`

```python
# ============================================================================
# CLAUDE CONTEXT - STAC METADATA EXTRACTION SERVICE
# ============================================================================
# PURPOSE: Extract and validate STAC metadata from geospatial files
# EXPORTS: StacMetadataService class
# PYDANTIC_MODELS: stac_pydantic.Item, stac_pydantic.Asset, stac_pydantic.Collection
# DEPENDENCIES: stac-pydantic, rasterio, rio-stac, pystac
# PATTERNS: Service Layer, Repository Pattern
# ============================================================================

from typing import Dict, Any, Optional, List
from stac_pydantic import Item, Asset, Collection
from stac_pydantic.shared import Link
import rasterio
from rio_stac import stac
from datetime import datetime, timezone
import logging

from config import Config
from repositories.blob import BlobRepository

logger = logging.getLogger(__name__)


class StacMetadataService:
    """
    Extract and validate STAC metadata from geospatial files.

    Uses stac-pydantic for strong typing and automatic validation.
    Integrates with BlobRepository for Azure Storage access.
    """

    def __init__(self, config: Config):
        self.config = config
        self.blob_repo = BlobRepository(config)

    def extract_from_blob(
        self,
        container: str,
        blob_path: str,
        collection_id: str,
        item_id: Optional[str] = None
    ) -> Item:
        """
        Extract STAC Item metadata from blob storage file.

        Args:
            container: Azure Storage container name
            blob_path: Path to blob within container
            collection_id: STAC collection this item belongs to
            item_id: Optional custom item ID (defaults to filename)

        Returns:
            Validated stac_pydantic.Item with full metadata

        Raises:
            ValidationError: If extracted metadata fails STAC validation
        """
        # Generate blob URL with SAS token
        blob_url = self.blob_repo.generate_blob_url(container, blob_path)

        # Extract metadata using rio-stac
        with rasterio.open(blob_url) as dataset:
            # rio-stac creates a dict following STAC Item spec
            item_dict = stac.create_stac_item(
                dataset,
                id=item_id or blob_path.replace('/', '_'),
                collection=collection_id,
                input_datetime=datetime.now(timezone.utc),
                asset_href=blob_url,
                asset_name="data"
            )

        # Validate and convert to Pydantic model
        # This automatically validates against STAC spec
        item = Item(**item_dict)

        logger.info(f"Extracted STAC Item: {item.id} from {blob_path}")
        return item

    def create_cog_asset(
        self,
        blob_url: str,
        title: Optional[str] = None,
        roles: Optional[List[str]] = None
    ) -> Asset:
        """
        Create a validated STAC Asset for a Cloud Optimized GeoTIFF.

        Args:
            blob_url: Full URL to COG in Azure Storage
            title: Human-readable asset title
            roles: Asset roles (data, thumbnail, overview, etc.)

        Returns:
            Validated stac_pydantic.Asset
        """
        asset = Asset(
            href=blob_url,
            type="image/tiff; application=geotiff; profile=cloud-optimized",
            title=title or "Cloud Optimized GeoTIFF",
            roles=roles or ["data"]
        )

        return asset

    def enrich_with_extensions(
        self,
        item: Item,
        eo_cloud_cover: Optional[float] = None,
        projection_epsg: Optional[int] = None
    ) -> Item:
        """
        Enrich STAC Item with extension properties.

        Args:
            item: Base STAC Item
            eo_cloud_cover: Cloud cover percentage (0-100)
            projection_epsg: EPSG code for projection

        Returns:
            Item with extension properties added and validated
        """
        # Add extension schemas
        extensions = list(item.stac_extensions or [])

        if eo_cloud_cover is not None:
            if "https://stac-extensions.github.io/eo/v1.0.0/schema.json" not in extensions:
                extensions.append("https://stac-extensions.github.io/eo/v1.0.0/schema.json")
            item.properties["eo:cloud_cover"] = eo_cloud_cover

        if projection_epsg is not None:
            if "https://stac-extensions.github.io/projection/v1.0.0/schema.json" not in extensions:
                extensions.append("https://stac-extensions.github.io/projection/v1.0.0/schema.json")
            item.properties["proj:epsg"] = projection_epsg

        item.stac_extensions = extensions

        # Validate extensions
        item.validate_extensions()

        return item

    def validate_item(self, item_dict: Dict[str, Any]) -> Item:
        """
        Validate arbitrary dict against STAC Item schema.

        Args:
            item_dict: Dictionary to validate

        Returns:
            Validated Item if valid

        Raises:
            ValidationError: If dict doesn't match STAC Item spec
        """
        return Item(**item_dict)
```

### Phase 3: Integration with PgSTAC

**File**: `infrastructure/stac.py` (add methods)

```python
def insert_item(
    self,
    item: Item,
    collection_id: str
) -> Dict[str, Any]:
    """
    Insert validated STAC Item into PgSTAC.

    Args:
        item: stac-pydantic Item (already validated)
        collection_id: Collection to insert item into

    Returns:
        Insertion result from PgSTAC
    """
    import json
    import psycopg

    # Convert Pydantic model to dict for PgSTAC
    item_dict = item.model_dump(mode='json', by_alias=True)

    with psycopg.connect(self.connection_string) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM pgstac.create_item(%s)",
                [json.dumps(item_dict)]
            )
            result = cur.fetchone()
            conn.commit()

            self.logger.info(f"Inserted STAC Item: {item.id} into {collection_id}")
            return {
                'success': True,
                'item_id': item.id,
                'collection': collection_id,
                'result': result
            }

def bulk_insert_items(
    self,
    items: List[Item],
    collection_id: str
) -> Dict[str, Any]:
    """
    Bulk insert validated STAC Items into PgSTAC.

    Args:
        items: List of stac-pydantic Items (already validated)
        collection_id: Collection to insert items into

    Returns:
        Bulk insertion results
    """
    import json
    import psycopg

    inserted = []
    failed = []

    with psycopg.connect(self.connection_string) as conn:
        with conn.cursor() as cur:
            for item in items:
                try:
                    item_dict = item.model_dump(mode='json', by_alias=True)
                    cur.execute(
                        "SELECT * FROM pgstac.create_item(%s)",
                        [json.dumps(item_dict)]
                    )
                    result = cur.fetchone()
                    inserted.append(item.id)
                except Exception as e:
                    failed.append({'item_id': item.id, 'error': str(e)})
                    self.logger.error(f"Failed to insert {item.id}: {e}")

            conn.commit()

    return {
        'success': len(failed) == 0,
        'inserted_count': len(inserted),
        'failed_count': len(failed),
        'inserted_items': inserted,
        'failed_items': failed
    }
```

## 🚀 Proposed Implementation Workflow

### Bronze Tier: Raw Raster → STAC Item
```
1. User uploads GeoTIFF to rmhazuregeobronze
2. Event trigger detects new blob
3. StacMetadataService.extract_from_blob() extracts metadata
4. stac-pydantic validates Item schema automatically
5. StacInfrastructure.insert_item() stores in PgSTAC
6. Item now queryable via STAC API
```

### Silver Tier: COG Creation → Update STAC Item
```
1. Job converts Bronze GeoTIFF to COG
2. COG stored in rmhazuregeosilver
3. StacMetadataService.create_cog_asset() creates Asset
4. Update existing Item with new COG asset
5. Original blob preserved in Bronze, COG in Silver
```

### Gold Tier: GeoParquet → New Collection
```
1. Job exports PostGIS → GeoParquet
2. Create new Collection for analytical datasets
3. Each GeoParquet is a STAC Item with tabular asset
4. Queryable via STAC API for data discovery
```

## 🎯 Advantages for Our Architecture

### 1. Type Safety
```python
# ✅ Pydantic catches errors at validation time
item = Item(
    id="test",
    type="Feature",  # Must be "Feature"
    bbox=[1, 2, 3, 4],  # Must be valid bbox
    geometry={"type": "Point", "coordinates": [0, 0]},
    properties={"datetime": "2025-10-05T00:00:00Z"}
)

# ❌ Pydantic raises ValidationError
item = Item(
    id="test",
    type="InvalidType",  # ERROR
    bbox=[1, 2],  # ERROR - invalid bbox
    geometry={"type": "InvalidGeometry"},  # ERROR
    properties={}  # ERROR - missing datetime
)
```

### 2. FastAPI Integration (Future)
```python
from fastapi import FastAPI
from stac_pydantic import Item

app = FastAPI()

@app.post("/stac/items", response_model=Item)
async def create_stac_item(item: Item) -> Item:
    # Request automatically validated
    # Response automatically serialized
    result = await stac_service.insert_item(item)
    return item
```

### 3. Extension Validation
```python
# Automatic validation against extension schemas
item.stac_extensions = [
    "https://stac-extensions.github.io/eo/v1.0.0/schema.json"
]
item.properties["eo:cloud_cover"] = 150  # ERROR - must be 0-100

item.validate_extensions()  # Validates against JSON schema
```

### 4. Consistent with Our Pydantic Philosophy
- **Contract enforcement**: Invalid STAC metadata caught immediately
- **Type hints**: Full IDE autocomplete and type checking
- **Documentation**: Self-documenting models with field descriptions
- **Validation**: Automatic validation at construction time

## 📋 Implementation Checklist

- [ ] Add `stac-pydantic>=3.4.0` to requirements.txt
- [ ] Create `services/service_stac_metadata.py`
- [ ] Add `insert_item()` and `bulk_insert_items()` to `infrastructure/stac.py`
- [ ] Create HTTP trigger for metadata extraction: `triggers/stac_items.py`
- [ ] Update `STAC_IMPLEMENTATION_PLAN.md` with stac-pydantic integration
- [ ] Test metadata extraction from Bronze container
- [ ] Test Item insertion into PgSTAC
- [ ] Deploy and verify end-to-end workflow

## 🎓 Learning Resources

- **Official Docs**: https://github.com/stac-utils/stac-pydantic
- **PyPI**: https://pypi.org/project/stac-pydantic/
- **STAC Spec**: https://stacspec.org/
- **Extensions**: https://stac-extensions.github.io/

## 🔑 Key Takeaway

**stac-pydantic is the perfect library for our Pydantic-authoritarian architecture.** It provides:

1. ✅ **Type safety** - Full Pydantic v2 models
2. ✅ **Automatic validation** - Catches errors immediately
3. ✅ **Extension support** - JSON schema validation
4. ✅ **FastAPI integration** - Native request/response models
5. ✅ **Consistent philosophy** - Matches our strong typing discipline

**Recommendation**: Adopt stac-pydantic as the primary library for all STAC metadata operations.
