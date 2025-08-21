# STAC Storage Analysis for Azure Geospatial ETL Pipeline

## Storage Options Comparison

### Option 1: Azure Table Storage (Current Architecture)
**Status**: Already implemented in `stac_models.py`

#### Pros ✅
- **Already integrated** - Models have `to_table_entity()` methods
- **Cost-effective** - ~$0.045/GB/month, pay per transaction
- **Simple deployment** - No additional infrastructure
- **Fast key-based lookups** - O(1) access by partition/row key
- **Serverless** - No management overhead
- **Good for small-medium catalogs** - Up to 100K items works well

#### Cons ❌
- **Limited query capabilities** - No spatial queries, basic filtering only
- **No GeoJSON queries** - Can't query by geometry natively
- **String-based storage** - Must serialize/deserialize JSON
- **500 entity batch limit** - Pagination required for large results
- **No aggregations** - Can't do COUNT, SUM, etc.
- **15KB property limit** - Large geometries might hit limits

#### Best Practices for Table Storage
```python
# Partition Strategy for efficient queries
Items Table:
  PartitionKey: "{collection_id}_{spatial_grid}"  # e.g., "bronze_37_31"
  RowKey: "{item_id}"

Collections Table:
  PartitionKey: "collections"
  RowKey: "{collection_id}"

# Spatial grid indexing for pseudo-spatial queries
spatial_grid = f"{int(lat/10)}_{int(lon/10)}"  # 10-degree grid
```

---

### Option 2: Azure Cosmos DB
**Status**: Better for production STAC at scale

#### Pros ✅
- **Native GeoJSON support** - Spatial queries with ST_INTERSECTS, ST_WITHIN
- **MongoDB API** - Compatible with existing STAC tools
- **Global distribution** - Multi-region replication
- **Automatic indexing** - Including spatial indexes
- **Rich queries** - SQL-like with aggregations
- **SLA guaranteed** - 99.99% availability
- **Unlimited scale** - Handles millions of items

#### Cons ❌
- **Higher cost** - ~$0.25/GB/month + RU consumption
- **More complex** - Requires provisioning and management
- **Learning curve** - Different query syntax
- **Not in current architecture** - Would need integration

#### Cosmos DB Schema
```json
{
  "id": "item_id",
  "type": "Feature",
  "geometry": {  // Automatically spatial-indexed
    "type": "Polygon",
    "coordinates": [...]
  },
  "properties": {...},
  "_collection": "bronze",  // For filtering
  "_ts": 1234567890  // Automatic timestamp
}
```

---

### Option 3: Hybrid Approach (Recommended for Production)
**Status**: Best of both worlds

#### Architecture
```
Table Storage (Metadata & Quick Lookups)
    ↓
Blob Storage (Full STAC JSON Files)
    ↓
Optional: Cosmos DB (Spatial Search Index)
```

#### Implementation
```python
class HybridSTACStorage:
    def store_item(self, item: STACItem):
        # 1. Store searchable fields in Table Storage
        table_entity = {
            'PartitionKey': item.collection,
            'RowKey': item.id,
            'bbox_west': item.bbox.west,
            'bbox_east': item.bbox.east,
            'bbox_north': item.bbox.north,
            'bbox_south': item.bbox.south,
            'datetime': item.datetime,
            'blob_path': f"stac/{item.collection}/{item.id}.json"
        }
        table_client.upsert_entity(table_entity)
        
        # 2. Store complete STAC JSON in Blob Storage
        stac_json = json.dumps(item.to_stac_dict(), indent=2)
        blob_client.upload_blob(
            name=f"stac/{item.collection}/{item.id}.json",
            data=stac_json,
            overwrite=True
        )
        
        # 3. Optional: Index in Cosmos DB for spatial queries
        if cosmos_enabled:
            cosmos_client.upsert_item(item.to_stac_dict())
```

---

### Option 4: Static STAC in Blob Storage
**Status**: Simplest for read-heavy workloads

#### Pros ✅
- **Dead simple** - Just JSON files in blob storage
- **CDN-friendly** - Can serve directly via CDN
- **STAC Browser compatible** - Works with static STAC tools
- **Lowest cost** - ~$0.0184/GB/month
- **Unlimited file size** - No entity limits

#### Cons ❌
- **No query capability** - Must download catalog to search
- **Slow discovery** - Need to traverse file structure
- **Update complexity** - Rebuilding indexes on changes

#### Structure
```
/stac/
  catalog.json
  /collections/
    bronze.json
    silver.json
  /bronze/
    /2023/
      item1.json
      item2.json
  /silver/
    /2023/
      item3.json
```

---

## Recommended Storage Strategy

### For Your Current Stage (MVP/Development) ✅
**Use Azure Table Storage** - It's already implemented and sufficient for:
- Thousands of items
- Basic filtering by collection, date range
- Quick development iteration
- Low operational cost

### For Production Scale (10K-100K items) 🚀
**Use Hybrid Approach**:
1. **Table Storage** - Quick lookups, basic queries
2. **Blob Storage** - Complete STAC JSONs, served via CDN
3. **Azure Search** (optional) - Full-text and basic spatial search

### For Large Scale (100K+ items) 🌍
**Migrate to Cosmos DB**:
- Full spatial query support
- STAC API compliance
- Global distribution
- Guaranteed performance

---

## Implementation Recommendations

### Phase 1: Start with Table Storage (Current)
```python
# Already implemented in stac_models.py
class STACRepository:
    def __init__(self):
        self.table_client = TableClient.from_connection_string(
            conn_str=Config.STORAGE_CONNECTION_STRING,
            table_name="stacitems"
        )
    
    def store_item(self, item: STACItem):
        entity = item.to_table_entity()
        self.table_client.upsert_entity(entity)
    
    def query_by_bbox(self, west, south, east, north):
        # Simple bbox overlap check
        filter = f"bbox_west <= {east} and bbox_east >= {west} and " \
                f"bbox_south <= {north} and bbox_north >= {south}"
        return self.table_client.query_entities(filter)
```

### Phase 2: Add Blob Storage for Complete STAC
```python
def store_stac_complete(self, item: STACItem):
    # Store searchable in Table
    self.store_item(item)
    
    # Store complete in Blob
    blob_name = f"stac/{item.collection}/{item.id}.json"
    blob_client = self.blob_service.get_blob_client(
        container="stac",
        blob=blob_name
    )
    blob_client.upload_blob(
        json.dumps(item.to_stac_dict(), indent=2),
        overwrite=True
    )
    
    # Return public URL
    return f"https://{account}.blob.core.windows.net/stac/{blob_name}"
```

### Phase 3: Add Spatial Indexing
```python
# Option A: Simple grid index in Table Storage
def get_spatial_grid(lat, lon, resolution=1.0):
    """Create spatial grid index for Table Storage partitioning"""
    grid_lat = int(lat / resolution) * resolution
    grid_lon = int(lon / resolution) * resolution
    return f"grid_{grid_lat}_{grid_lon}"

# Option B: H3 Hexagonal indexing
import h3
def get_h3_index(lat, lon, resolution=7):
    """Use Uber's H3 for efficient spatial indexing"""
    return h3.geo_to_h3(lat, lon, resolution)
```

---

## Cost Analysis (Monthly)

### For 10,000 STAC Items:

| Storage Type | Storage Cost | Transaction Cost | Total |
|--------------|-------------|------------------|-------|
| Table Storage | ~$0.05 | ~$1.00 | **~$1.05** |
| Cosmos DB | ~$25.00 | ~$10.00 | ~$35.00 |
| Hybrid (Table+Blob) | ~$0.10 | ~$1.50 | **~$1.60** |
| Static Blob | ~$0.02 | ~$0.50 | **~$0.52** |

### For 100,000 STAC Items:

| Storage Type | Storage Cost | Transaction Cost | Total |
|--------------|-------------|------------------|-------|
| Table Storage | ~$0.50 | ~$10.00 | **~$10.50** |
| Cosmos DB | ~$250.00 | ~$100.00 | ~$350.00 |
| Hybrid (Table+Blob) | ~$1.00 | ~$15.00 | **~$16.00** |
| Static Blob | ~$0.20 | ~$5.00 | ~$5.20 |

---

## SQL Query Examples

### Table Storage (OData filters)
```python
# Simple bbox query
filter = f"PartitionKey eq '{collection}' and " \
         f"bbox_west le {east} and bbox_east ge {west}"

# Date range query  
filter = f"datetime ge '{start_date}' and datetime le '{end_date}'"
```

### Cosmos DB (SQL API)
```sql
-- Spatial intersection query
SELECT * FROM c 
WHERE ST_INTERSECTS(c.geometry, {
  "type": "Polygon",
  "coordinates": [[[36.0, 31.9], [36.1, 31.9], [36.1, 32.0], [36.0, 32.0], [36.0, 31.9]]]
})

-- Complex query with aggregation
SELECT COUNT(1) as count, AVG(c.properties.gsd) as avg_gsd
FROM c
WHERE c.collection = 'bronze' 
  AND c.properties.datetime >= '2023-01-01'
  AND ST_WITHIN(c.geometry, @search_polygon)
```

---

## Decision Matrix

| Criteria | Table Storage | Cosmos DB | Hybrid | Static |
|----------|--------------|-----------|--------|--------|
| Setup Complexity | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ |
| Query Capability | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐ |
| Spatial Queries | ⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ❌ |
| Cost Efficiency | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| Scalability | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| STAC Compliance | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| Dev Speed | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ |

---

## Final Recommendation

### Start Now (Week 1-4): ✅
**Use Table Storage** 
- Already implemented in `stac_models.py`
- Sufficient for MVP and early production
- Can handle up to 50K items effectively
- Cost: ~$1-10/month

### Near Future (Month 2-3): 🚀
**Add Blob Storage for complete STAC JSONs**
- Store full STAC in blobs
- Keep searchable fields in Table Storage
- Serve via CDN for performance
- Cost: ~$10-20/month

### Scale Phase (Month 6+): 🌍
**Evaluate Cosmos DB or PostgreSQL with PostGIS**
- When you need true spatial queries
- When you have 100K+ items
- When you need STAC API compliance
- Cost: ~$100-500/month

### Code to Start Today:
```python
# The models are already there! Just need to:
1. Create the tables in Azure
2. Implement the STACGenerationService
3. Add to the processing pipeline
4. Test with real data

# Tables needed:
- staccollections
- stacitems
```

The beauty is that the `stac_models.py` already has everything needed for Table Storage. You can literally start using it today and migrate to a more sophisticated solution when needed. The migration path is clear:

**Table Storage → Table + Blob → Table + Blob + Cosmos/PostGIS**