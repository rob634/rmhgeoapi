# TiTiler STAC Integration Quick Guide

**For:** Geospatial ETL Pipeline Team
**Date:** November 7, 2025
**Production Endpoint:** `https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net`

---

## TL;DR - Essential URL Patterns

When creating STAC catalog entries for COGs in the `silver-cogs` container, use these URL patterns:

### 1. Metadata Endpoint
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/info?url=/vsiaz/silver-cogs/{blob_name}
```
**Use for:** Extracting bounds, CRS, band info, dimensions for STAC item properties

### 2. GeoJSON Bounds
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/info.geojson?url=/vsiaz/silver-cogs/{blob_name}
```
**Use for:** STAC item geometry (already in GeoJSON format)

### 3. Statistics
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/statistics?url=/vsiaz/silver-cogs/{blob_name}
```
**Use for:** Band statistics (min, max, mean, stddev) for `raster:bands` property

### 4. Thumbnail Preview
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/preview.png?url=/vsiaz/silver-cogs/{blob_name}&max_size=256
```
**Use for:** STAC item thumbnail asset

### 5. Interactive Viewer (IMPORTANT!)
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/WebMercatorQuad/map.html?url=/vsiaz/silver-cogs/{blob_name}
```
**Use for:** STAC item link with `rel: "preview"`
**Note:** The endpoint is `/cog/WebMercatorQuad/map.html`, NOT `/cog/viewer` (common mistake!)

### 6. TileJSON Specification
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/WebMercatorQuad/tilejson.json?url=/vsiaz/silver-cogs/{blob_name}
```
**Use for:** STAC item link with `rel: "tilejson"` (for web map integration)

### 7. XYZ Tile Template
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png?url=/vsiaz/silver-cogs/{blob_name}
```
**Use for:** Dynamic tile serving in STAC visualizers

---

## Python Integration Example

```python
import requests
from typing import Dict

TITILER_BASE = "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net"
CONTAINER = "silver-cogs"

def create_stac_item(blob_name: str) -> Dict:
    """
    Create STAC item with TiTiler visualization links.

    Args:
        blob_name: COG filename in silver-cogs container

    Returns:
        STAC item dictionary
    """
    cog_url = f"/vsiaz/{CONTAINER}/{blob_name}"

    # Get metadata
    info = requests.get(f"{TITILER_BASE}/cog/info?url={cog_url}").json()
    geojson = requests.get(f"{TITILER_BASE}/cog/info.geojson?url={cog_url}").json()
    stats = requests.get(f"{TITILER_BASE}/cog/statistics?url={cog_url}").json()

    # Build STAC item
    stac_item = {
        "type": "Feature",
        "stac_version": "1.0.0",
        "id": blob_name.replace(".tif", ""),
        "geometry": geojson["geometry"],
        "bbox": info["bounds"],
        "properties": {
            "datetime": "...",  # Add your timestamp
            "proj:shape": [info["height"], info["width"]],
        },
        "assets": {
            "cog": {
                "href": f"https://rmhazuregeo.blob.core.windows.net/{CONTAINER}/{blob_name}",
                "type": "image/tiff; application=geotiff; profile=cloud-optimized",
                "roles": ["data"],
                "raster:bands": [
                    {
                        "data_type": info["dtype"],
                        "statistics": {
                            "minimum": stats[band]["min"],
                            "maximum": stats[band]["max"],
                            "mean": stats[band]["mean"],
                            "stddev": stats[band]["std"]
                        }
                    }
                    for band in stats.keys()
                ]
            },
            "thumbnail": {
                "href": f"{TITILER_BASE}/cog/preview.png?url={cog_url}&max_size=256",
                "type": "image/png",
                "roles": ["thumbnail"]
            }
        },
        "links": [
            {
                "rel": "preview",
                "href": f"{TITILER_BASE}/cog/WebMercatorQuad/map.html?url={cog_url}",
                "type": "text/html",
                "title": "Interactive map viewer"
            },
            {
                "rel": "tilejson",
                "href": f"{TITILER_BASE}/cog/WebMercatorQuad/tilejson.json?url={cog_url}",
                "type": "application/json",
                "title": "TileJSON for web maps"
            }
        ]
    }

    return stac_item

# Example usage
stac_item = create_stac_item("copy47_of_dctest3_R1C2_cog_analysis.tif")
```

---

## Key Points for ETL Pipeline

1. **COG URL Format:** Always use `/vsiaz/{container}/{blob_path}` - this is GDAL's virtual file system syntax

2. **Viewer Endpoint:** The correct viewer path is `/cog/WebMercatorQuad/map.html`, NOT `/cog/viewer`

3. **Tile Matrix Sets:**
   - `WebMercatorQuad` - EPSG:3857 (standard web maps) - **Use this one**
   - `WorldCRS84Quad` - EPSG:4326 (geographic coordinates)

4. **Health Check:** Check `https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/healthz` before batch processing to ensure service is ready

5. **Error Handling:**
   - HTTP 404: COG not found or path incorrect
   - HTTP 403: Authentication issue (check `/healthz` for SAS token status)
   - HTTP 500: Server error (retry with backoff)

6. **Rate Limiting:** Current setup has 1 worker - limit to 10-20 concurrent requests max during batch processing

---

## Complete Example: Full STAC Item

```json
{
  "type": "Feature",
  "stac_version": "1.0.0",
  "id": "copy47_of_dctest3_R1C2_cog_analysis",
  "geometry": {
    "type": "Polygon",
    "coordinates": [[...]]
  },
  "bbox": [-93.7037, 41.9637, -93.6912, 41.9736],
  "properties": {
    "datetime": "2025-11-07T00:00:00Z",
    "proj:shape": [12288, 12288]
  },
  "assets": {
    "cog": {
      "href": "https://rmhazuregeo.blob.core.windows.net/silver-cogs/copy47_of_dctest3_R1C2_cog_analysis.tif",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "roles": ["data"]
    },
    "thumbnail": {
      "href": "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/preview.png?url=/vsiaz/silver-cogs/copy47_of_dctest3_R1C2_cog_analysis.tif&max_size=256",
      "type": "image/png",
      "roles": ["thumbnail"]
    }
  },
  "links": [
    {
      "rel": "preview",
      "href": "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/WebMercatorQuad/map.html?url=/vsiaz/silver-cogs/copy47_of_dctest3_R1C2_cog_analysis.tif",
      "type": "text/html",
      "title": "Interactive map viewer"
    },
    {
      "rel": "tilejson",
      "href": "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/WebMercatorQuad/tilejson.json?url=/vsiaz/silver-cogs/copy47_of_dctest3_R1C2_cog_analysis.tif",
      "type": "application/json",
      "title": "TileJSON specification"
    }
  ]
}
```

---

## Testing Commands

```bash
# Test metadata extraction
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/info?url=/vsiaz/silver-cogs/copy47_of_dctest3_R1C2_cog_analysis.tif" | jq

# Test GeoJSON bounds
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/info.geojson?url=/vsiaz/silver-cogs/copy47_of_dctest3_R1C2_cog_analysis.tif" | jq

# Test statistics
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/statistics?url=/vsiaz/silver-cogs/copy47_of_dctest3_R1C2_cog_analysis.tif" | jq

# Test viewer (open in browser)
open "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/WebMercatorQuad/map.html?url=/vsiaz/silver-cogs/copy47_of_dctest3_R1C2_cog_analysis.tif"
```

---

## Documentation References

- **Complete API Reference:** [TITILER-API-REFERENCE.md](TITILER-API-REFERENCE.md) - Full endpoint documentation with code examples
- **Deployment Troubleshooting:** [DEPLOYMENT-TROUBLESHOOTING.md](DEPLOYMENT-TROUBLESHOOTING.md) - Production deployment details and fixes
- **Authentication Details:** [AUTHENTICATION-VERIFICATION.md](AUTHENTICATION-VERIFICATION.md) - How managed identity authentication works

---

## Support

**Service Status:** Production ready
**Version:** 1.0.2
**Container:** rmhazuregeo / silver-cogs
**Authentication:** Azure Managed Identity with User Delegation SAS tokens

**Health Check:**
```bash
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/healthz"
```

Expected response:
```json
{
  "status": "healthy",
  "azure_auth_enabled": true,
  "use_sas_token": true,
  "local_mode": false,
  "storage_account": "rmhazuregeo",
  "sas_token_expires_in_seconds": 3585
}
```

---

**Questions?** Check the full API reference at [TITILER-API-REFERENCE.md](TITILER-API-REFERENCE.md)
