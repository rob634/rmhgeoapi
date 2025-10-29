# TiTiler Non-STAC Usage (Direct COG Access)

**Date**: 28 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: How to use TiTiler without STAC, directly with COG URLs

## Overview

TiTiler can work in two modes:
1. **TiTiler-PgSTAC**: Reads from STAC catalog in PostgreSQL (current deployment)
2. **TiTiler-Core**: Direct COG access via URL parameters (also available!)

## Direct COG Access (No STAC Required)

### Basic Pattern

Instead of querying STAC, you pass the COG URL directly as a query parameter:

```bash
# Base pattern
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/tiles/{z}/{x}/{y}?url={COG_URL}
```

### Examples

#### 1. Get Tile from Azure Blob Storage COG
```bash
# Direct tile request
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/tiles/10/256/512.png?url=https://rmhazuregeo.blob.core.windows.net/rmhazuregeocogs/antigua.tif"

# URL-encoded version (safer for special characters)
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/tiles/10/256/512.png?url=https%3A%2F%2Frmhazuregeo.blob.core.windows.net%2Frmhazuregeocogs%2Fantigua.tif"
```

#### 2. Get COG Metadata
```bash
# Get bounds, bands, statistics
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/info?url=https://rmhazuregeo.blob.core.windows.net/rmhazuregeocogs/antigua.tif"
```

#### 3. Get COG Statistics
```bash
# Get min/max values per band
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/statistics?url=https://rmhazuregeo.blob.core.windows.net/rmhazuregeocogs/antigua.tif"
```

#### 4. Generate TileJSON
```bash
# Get TileJSON for map clients
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/tilejson.json?url=https://rmhazuregeo.blob.core.windows.net/rmhazuregeocogs/antigua.tif"
```

#### 5. Preview Map
```bash
# Interactive map viewer
open "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/viewer?url=https://rmhazuregeo.blob.core.windows.net/rmhazuregeocogs/antigua.tif"
```

## Available Endpoints (Non-STAC)

### Core COG Endpoints

| Endpoint | Description | Example |
|----------|-------------|---------|
| `/cog/tiles/{z}/{x}/{y}` | Get a single tile | `?url={cog_url}` |
| `/cog/info` | Get COG metadata | `?url={cog_url}` |
| `/cog/statistics` | Get band statistics | `?url={cog_url}` |
| `/cog/tilejson.json` | Get TileJSON | `?url={cog_url}` |
| `/cog/WMTSCapabilities.xml` | Get WMTS capabilities | `?url={cog_url}` |
| `/cog/bounds` | Get geographic bounds | `?url={cog_url}` |
| `/cog/preview` | Generate preview image | `?url={cog_url}` |
| `/cog/viewer` | Interactive map viewer | `?url={cog_url}` |

### Advanced Parameters

#### Styling Parameters
```bash
# Adjust contrast and colors
?url={cog_url}&rescale=0,255&colormap_name=viridis

# Select specific bands (for multi-band imagery)
?url={cog_url}&bands=1,2,3  # RGB
?url={cog_url}&bands=4,3,2  # False color

# Apply color formula
?url={cog_url}&color_formula=gamma RGB 3.5
```

#### Performance Parameters
```bash
# Lower resolution for faster preview
?url={cog_url}&max_size=512

# Specify exact resolution
?url={cog_url}&width=256&height=256
```

## URL Formats Supported

TiTiler can access COGs from various sources:

### 1. Azure Blob Storage (Your Setup)
```
https://rmhazuregeo.blob.core.windows.net/rmhazuregeocogs/filename.tif
https://rmhazuregeo.blob.core.windows.net/container/path/to/cog.tif
```

### 2. Public HTTP/HTTPS
```
https://example.com/path/to/cog.tif
http://data.example.org/imagery/cog.tif
```

### 3. S3 (Public or with credentials)
```
s3://bucket/path/to/cog.tif
https://bucket.s3.amazonaws.com/path/to/cog.tif
```

## Authentication for Non-STAC Access

The managed identity you configured works for ALL Azure Storage access:

1. **Public Blobs**: No authentication needed
2. **Private Blobs in rmhazuregeo**: Managed identity automatically authenticates
3. **Cross-Account Access**: Would need additional role assignments

## JavaScript/Leaflet Integration Example

```javascript
// Direct COG access in Leaflet
const cogUrl = 'https://rmhazuregeo.blob.core.windows.net/rmhazuregeocogs/antigua.tif';
const titilerUrl = 'https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net';

// Add COG as tile layer (no STAC needed!)
const cogLayer = L.tileLayer(
  `${titilerUrl}/cog/tiles/{z}/{x}/{y}.png?url=${encodeURIComponent(cogUrl)}`,
  {
    attribution: 'COG via TiTiler',
    minZoom: 0,
    maxZoom: 18
  }
).addTo(map);

// Get COG bounds and fit map
fetch(`${titilerUrl}/cog/bounds?url=${encodeURIComponent(cogUrl)}`)
  .then(res => res.json())
  .then(data => {
    map.fitBounds([[data.bounds[1], data.bounds[0]], [data.bounds[3], data.bounds[2]]]);
  });
```

## Python Integration Example

```python
import requests
from urllib.parse import quote

# Direct COG access
cog_url = "https://rmhazuregeo.blob.core.windows.net/rmhazuregeocogs/antigua.tif"
titiler_url = "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net"

# Get COG info
info = requests.get(f"{titiler_url}/cog/info", params={"url": cog_url}).json()
print(f"Bounds: {info['bounds']}")
print(f"Bands: {info['band_descriptions']}")

# Get a tile
tile_response = requests.get(
    f"{titiler_url}/cog/tiles/10/256/512.png",
    params={"url": cog_url}
)
with open("tile.png", "wb") as f:
    f.write(tile_response.content)
```

## Advantages of Direct COG Access

### Pros:
- ✅ No database required
- ✅ No STAC catalog maintenance
- ✅ Works with any COG URL
- ✅ Simple URL-based API
- ✅ Can access COGs from multiple sources

### Cons:
- ❌ No metadata search/filtering
- ❌ No collection management
- ❌ Must know exact COG URLs
- ❌ No temporal or spatial queries
- ❌ Harder to manage large datasets

## Mixed Mode Usage

You can use BOTH STAC and non-STAC endpoints in the same TiTiler instance:

```bash
# STAC-based (catalog item)
/stac/tiles/{z}/{x}/{y}?url={stac_item_url}

# Direct COG (no catalog)
/cog/tiles/{z}/{x}/{y}?url={cog_blob_url}

# Both work simultaneously!
```

## Testing Direct Access

Quick test with your COGs:

```bash
# 1. Upload a test COG to storage
az storage blob upload \
  --account-name rmhazuregeo \
  --container-name rmhazuregeocogs \
  --name test.tif \
  --file ./antigua.tif

# 2. Get metadata
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/info?url=https://rmhazuregeo.blob.core.windows.net/rmhazuregeocogs/test.tif"

# 3. View in browser
open "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/viewer?url=https://rmhazuregeo.blob.core.windows.net/rmhazuregeocogs/test.tif"
```

## Common Use Cases

### When to Use Direct COG Access:
1. **Quick visualization** of individual COGs
2. **Testing** COG validity before STAC ingestion
3. **Simple applications** with known COG URLs
4. **External COGs** not in your STAC catalog
5. **Temporary/preview** visualizations

### When to Use STAC:
1. **Large collections** of imagery
2. **Temporal queries** (time series)
3. **Spatial searches** (bbox, geometry)
4. **Metadata filtering** (cloud cover, sensor)
5. **Production applications** with complex queries

## Summary

- **Yes, you can use TiTiler without STAC** - just pass the blob URL
- **Same authentication** - Managed identity works for both modes
- **Same deployment** - No changes needed to your Web App
- **URL parameter** - Simply add `?url={cog_blob_url}` to endpoints
- **Both modes available** - Use STAC when needed, direct COG when simpler