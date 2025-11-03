# TiTiler-PgSTAC Working Endpoints

**Base URL**: `https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net`

**Status**: ✅ All endpoints tested and working (2 NOV 2025)

---

## 🌐 Browser-Ready URLs (Click to Open)

### **Core Endpoints**

| Endpoint | Description | Status | Browser URL |
|----------|-------------|--------|-------------|
| **Landing Page** | Main entry point with all links | ✅ Working | https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/ |
| **API Documentation** | Interactive Swagger UI | ✅ Working | https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/api.html |
| **OpenAPI Spec** | JSON API specification | ✅ Working | https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/api |
| **Health Check** | Service health status | ✅ Working | https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/healthz |
| **OGC Conformance** | Standards compliance | ✅ Working | https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/conformance |

---

### **STAC Collection Endpoints**

| Endpoint | Description | Status | Browser URL |
|----------|-------------|--------|-------------|
| **List All Collections** | Array of collection IDs | ✅ Working | https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/collections |
| **Dev Collection** | Development/testing collection | ✅ Working | https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/collections/dev |
| **COGs Collection** | Cloud-Optimized GeoTIFFs | ✅ Working | https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/collections/cogs |
| **Vectors Collection** | Vector datasets | ✅ Working | https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/collections/vectors |
| **GeoParquet Collection** | GeoParquet exports | ✅ Working | https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/collections/geoparquet |
| **System Vectors** | System vector tracking | ✅ Working | https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/collections/system-vectors |
| **System Rasters** | System raster tracking | ✅ Working | https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/collections/system-rasters |

---

### **Configuration & Metadata Endpoints**

| Endpoint | Description | Status | Browser URL |
|----------|-------------|--------|-------------|
| **Tile Matrix Sets** | Available coordinate systems (13 sets) | ✅ Working | https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/tileMatrixSets |
| **ColorMaps** | Available color ramps for visualization | ✅ Working | https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/colorMaps |
| **Algorithms** | Available processing algorithms | ✅ Working | https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/algorithms |
| **Saved Searches** | List of registered PgSTAC searches | ✅ Working | https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/searches/list |

---

## 📊 **Available Collections Details**

### **Collections Summary**

```json
[
  "dev",              // Development/testing
  "cogs",            // Cloud-Optimized GeoTIFFs (your main raster data!)
  "vectors",         // Vector datasets
  "geoparquet",      // GeoParquet exports
  "system-vectors",  // System vector tracking
  "system-rasters"   // System raster tracking
]
```

### **COGs Collection Details**

```json
{
  "id": "cogs",
  "type": "Collection",
  "title": "Cloud-Optimized GeoTIFFs",
  "description": "Raster data converted to COG format in EPSG:4326 for cloud-native access",
  "license": "proprietary",
  "stac_version": "1.0.0",
  "extent": {
    "spatial": {"bbox": [[-180, -90, 180, 90]]},
    "temporal": {"interval": [[null, null]]}
  },
  "summaries": {
    "asset_type": ["raster"],
    "media_type": ["image/tiff; application=geotiff; profile=cloud-optimized"]
  }
}
```

**Status**: Collection exists but has **no items yet** (need to process rasters through your ETL pipeline)

---

## 🗺️ **Tile Serving Endpoints** (Template URLs)

These endpoints will work once you have STAC items with COG assets in the collections:

### **Collection-Level Tiles**

```
GET /collections/{collection_id}/{tileMatrixSetId}/tiles/{z}/{x}/{y}
```

**Example** (once items exist):
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/collections/cogs/WebMercatorQuad/tiles/10/512/384
```

### **Item-Level Tiles**

```
GET /collections/{collection_id}/items/{item_id}/{tileMatrixSetId}/tiles/{z}/{x}/{y}
```

**Example** (once you process a raster named "17apr2024wv2"):
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/collections/cogs/items/17apr2024wv2/WebMercatorQuad/tiles/10/512/384
```

### **Item Preview**

```
GET /collections/{collection_id}/items/{item_id}/preview.png?width=512
```

**Example**:
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/collections/cogs/items/17apr2024wv2/preview.png?width=512
```

### **Item Info**

```
GET /collections/{collection_id}/items/{item_id}/info
```

**Example**:
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/collections/cogs/items/17apr2024wv2/info
```

### **Item Bounds**

```
GET /collections/{collection_id}/items/{item_id}/bounds
```

**Example**:
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/collections/cogs/items/17apr2024wv2/bounds
```

---

## 🎨 **Tile Styling Parameters**

Add these query parameters to tile requests for custom rendering:

### **Color Ramps**
```
?colormap=viridis
?colormap=terrain
?colormap=turbo
```

### **Band Selection**
```
?assets=red,green,blue
?bidx=1,2,3
```

### **Rescaling**
```
?rescale=0,255
?rescale=0,3000
```

### **Format**
```
?format=png
?format=jpeg
?format=tif
?format=webp
```

### **Combined Example**
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/collections/cogs/items/17apr2024wv2/WebMercatorQuad/tiles/10/512/384?colormap=terrain&rescale=0,3000&format=png
```

---

## 📍 **Interactive Map Viewers** (Template URLs)

TiTiler provides built-in map viewers:

### **Item Viewer**
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/collections/{collection_id}/items/{item_id}/WebMercatorQuad/map.html
```

**Example**:
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/collections/cogs/items/17apr2024wv2/WebMercatorQuad/map.html
```

### **Collection Viewer**
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/collections/{collection_id}/WebMercatorQuad/map.html
```

---

## 🔍 **Available Tile Matrix Sets** (Coordinate Systems)

TiTiler supports **13 tile matrix sets**:

1. **WebMercatorQuad** - Standard web maps (Google/Leaflet/Mapbox)
2. **WorldCRS84Quad** - WGS84 geographic (EPSG:4326)
3. **WorldMercatorWGS84Quad** - Mercator projection
4. **CDB1GlobalGrid** - CDB standard
5. **CanadianNAD83_LCC** - Canada Lambert Conformal Conic
6. **EuropeanETRS89_LAEAQuad** - European projection
7. **GNOSISGlobalGrid** - GNOSIS standard
8. **LINZAntarticaMapTilegrid** - Antarctica
9. **NZTM2000Quad** - New Zealand
10. **UTM31WGS84Quad** - UTM Zone 31
11. **UPSAntarcticWGS84Quad** - Antarctic Polar Stereographic
12. **UPSArcticWGS84Quad** - Arctic Polar Stereographic
13. **WGS1984Quad** - WGS84 plate carrée

**Most Common**: Use `WebMercatorQuad` for standard web mapping

---

## 🚦 **Health Check Response**

```json
{
  "database_online": true,
  "versions": {
    "titiler": "0.24.0",
    "titiler.pgstac": "1.9.0",
    "rasterio": "1.4.3",
    "gdal": "3.9.3",
    "proj": "9.4.1",
    "geos": "3.11.1"
  }
}
```

---

## ⚠️ **Important Notes**

### **No Items Yet**

The collections exist but have **no STAC items yet**. You need to:

1. Run your raster processing pipeline (`process_large_raster` job)
2. This will create:
   - Individual COG tiles in Azure Storage
   - MosaicJSON in `silver/mosaics/` folder
   - STAC Item in the `cogs` collection with MosaicJSON asset
3. Then TiTiler can serve tiles from those items

### **Testing Workflow**

Once you process a raster:

```bash
# 1. Verify STAC item exists
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/collections/cogs/items/{your_item_id}"

# 2. Get item info
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/collections/cogs/items/{your_item_id}/info"

# 3. Get preview image
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/collections/cogs/items/{your_item_id}/preview.png?width=512" -o preview.png

# 4. Open interactive map
open "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/collections/cogs/items/{your_item_id}/WebMercatorQuad/map.html"
```

---

## 🎯 **OGC API Compliance**

TiTiler-PgSTAC conforms to these OGC standards:

- ✅ **OGC API - Common 1.0** (Core, HTML, JSON, Landing Page, OAS30)
- ✅ **OGC API - Tiles 1.0** (Core, JPEG, PNG, TIFF, Tileset, Tilesets List)

This means it's fully interoperable with other OGC-compliant tools!

---

## 📚 **Documentation Links**

- **Interactive API Docs**: https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/api.html
- **TiTiler-PgSTAC Docs**: https://stac-utils.github.io/titiler-pgstac/
- **GitHub**: https://github.com/stac-utils/titiler-pgstac
- **STAC Specification**: https://stacspec.org/

---

## ✅ **Next Steps**

1. **Process a test raster** through your `process_large_raster` pipeline
2. **Verify STAC item created** in the `cogs` collection
3. **Test tile serving** using the endpoints above
4. **Open interactive map** to visualize your COGs!

---

**Last Updated**: 2 NOV 2025
**TiTiler Version**: 0.24.0
**TiTiler-PgSTAC Version**: 1.9.0
**Database**: geopgflex (PostgreSQL with PgSTAC 0.8.5)