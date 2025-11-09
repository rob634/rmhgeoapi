# TiTiler Deployment Documentation

**Date**: 7 NOV 2025 (Updated - Vanilla TiTiler Deployed!)
**Author**: Robert and Geospatial Claude Legion

## Overview

This folder contains documentation for **Vanilla TiTiler** deployment on Azure. TiTiler is a dynamic tile server that generates map tiles on-the-fly from Cloud-Optimized GeoTIFFs (COGs) stored in Azure Blob Storage.

**🎉 MAJOR UPDATE (7 NOV 2025):** Successfully migrated from TiTiler-PgSTAC to **Vanilla TiTiler** with direct `/vsiaz/` access to Azure Blob Storage - no database dependency required!

## Current Deployment Status ✅

**Active Web App**: `rmhtitiler`
**Docker Image**: `ghcr.io/developmentseed/titiler:latest` (Vanilla TiTiler)
**Authentication**: Azure Storage Account Key + GDAL `/vsiaz/` driver
**Status**: **PRODUCTION READY** - All endpoints operational!

**Deployment URL:**
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net
```

## What Changed - TiTiler-PgSTAC → Vanilla TiTiler

### Before (TiTiler-PgSTAC)
- Required PgSTAC database for COG catalog
- Complex three-tier architecture (STAC API → PgSTAC → TiTiler)
- Database queries for every tile request
- Limited to STAC-cataloged items only

### After (Vanilla TiTiler) ✅
- **No database required** for tile serving
- Direct `/vsiaz/` access to Azure Blob Storage COGs
- Simpler architecture: URL → TiTiler → COG → Tiles
- Works with ANY COG in blob storage (cataloged or not!)
- Faster response times (no database latency)

## Architecture

### Simple Flow (Current)
```
1. Client: GET /cog/tiles/{z}/{x}/{y}?url=/vsiaz/{container}/{blob}
                              ↓
2. TiTiler: Opens COG via GDAL /vsiaz/ driver
                              ↓
3. Azure Storage: Returns COG data (authenticated via account key)
                              ↓
4. TiTiler: Generates tile → Returns PNG/JPEG to client
```

**No database, no intermediate services - just direct COG access!**

## Key Configuration Changes (7 NOV 2025)

### 1. Docker Image Updated
```bash
# Old: TiTiler-PgSTAC
ghcr.io/stac-utils/titiler-pgstac:latest

# New: Vanilla TiTiler
ghcr.io/developmentseed/titiler:latest
```

### 2. Environment Variables

**Removed (PgSTAC-specific):**
- `POSTGRES_HOST`
- `POSTGRES_DBNAME`
- `POSTGRES_USER`
- `POSTGRES_PASS`
- `POSTGRES_PORT`
- `POSTGRES_SCHEMA`

**Added (Azure Storage + GDAL):**
```bash
# Azure Storage Authentication (GDAL /vsiaz/ driver)
AZURE_STORAGE_ACCOUNT=rmhazuregeo
AZURE_STORAGE_ACCESS_KEY=<storage_key>

# GDAL Performance Tuning
CPL_VSIL_CURL_ALLOWED_EXTENSIONS=.tif,.TIF,.tiff
GDAL_CACHEMAX=200
GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR
GDAL_HTTP_MERGE_CONSECUTIVE_RANGES=YES
GDAL_HTTP_MULTIPLEX=YES
GDAL_HTTP_VERSION=2
VSI_CACHE=TRUE
VSI_CACHE_SIZE=5000000

# CORS & Proxy Headers (CRITICAL for HTTPS viewer)
TITILER_CORS_ORIGINS=*
FORWARDED_ALLOW_IPS=*  # ← Fixes mixed content errors in browser!
```

### 3. HTTPS Mixed Content Fix 🔧

**Problem:** Viewer loaded over HTTPS but generated HTTP API URLs → Browser blocked (mixed content error)

**Root Cause:** Azure App Service terminates SSL at load balancer, internal traffic to container is HTTP. TiTiler's FastAPI `request.base_url` saw HTTP.

**Solution:** Set `FORWARDED_ALLOW_IPS=*` to trust Azure's `X-Forwarded-Proto: https` headers.

**Result:** ✅ Viewer now correctly generates HTTPS URLs for all API endpoints!

## Working Endpoints

### 🗺️ Interactive Viewer (WORKING!)
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/viewer?url=/vsiaz/{container}/{blob}
```

**Example:**
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/viewer?url=%2Fvsiaz%2Fsilver-cogs%2F05APR13082706_cog_analysis.tif
```

### 📊 COG Metadata
```bash
# Get COG information (bounds, CRS, bands, etc.)
GET /cog/info?url=/vsiaz/{container}/{blob}

# Example
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/info?url=/vsiaz/silver-cogs/05APR13082706_cog_analysis.tif"
```

### 🎨 TileJSON Specification
```bash
# Get TileJSON (zoom levels, bounds, tile URL template)
GET /cog/WebMercatorQuad/tilejson.json?url=/vsiaz/{container}/{blob}

# Example
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/WebMercatorQuad/tilejson.json?url=/vsiaz/rmhazuregeobronze/05APR13082706.tif"
```

### 🗺️ Map Tiles (XYZ)
```bash
# Get individual tile
GET /cog/tiles/WebMercatorQuad/{z}/{x}/{y}?url=/vsiaz/{container}/{blob}

# Example
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/tiles/WebMercatorQuad/15/19665/13317?url=/vsiaz/rmhazuregeobronze/05APR13082706.tif"
```

### 📈 Statistics
```bash
# Get band statistics
GET /cog/statistics?url=/vsiaz/{container}/{blob}
```

### 📖 API Documentation
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/docs
```

## Integration with Process Raster Pipeline

Your `process_raster` job creates COGs in `silver-cogs` container. Use them directly in TiTiler:

```bash
# 1. Submit raster processing job
curl -X POST "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/process_raster" \
  -H "Content-Type: application/json" \
  -d '{
    "blob_name": "05APR13082706.tif",
    "container_name": "rmhazuregeobronze"
  }'

# 2. Job completes → COG created in silver-cogs/05APR13082706_cog_analysis.tif

# 3. View in TiTiler immediately (no catalog update needed!)
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/viewer?url=%2Fvsiaz%2Fsilver-cogs%2F05APR13082706_cog_analysis.tif
```

**Key Benefit:** New COGs are instantly available in TiTiler without any database updates or catalog synchronization!

## Deployment Commands

### View Current Configuration
```bash
az webapp config appsettings list \
  --resource-group rmhazure_rg \
  --name rmhtitiler \
  --output table
```

### Update Docker Image
```bash
az webapp config container set \
  --name rmhtitiler \
  --resource-group rmhazure_rg \
  --docker-custom-image-name ghcr.io/developmentseed/titiler:latest
```

### Add/Update Environment Variables
```bash
az webapp config appsettings set \
  --name rmhtitiler \
  --resource-group rmhazure_rg \
  --settings \
    AZURE_STORAGE_ACCOUNT=rmhazuregeo \
    AZURE_STORAGE_ACCESS_KEY=<key> \
    FORWARDED_ALLOW_IPS=* \
    TITILER_CORS_ORIGINS=*
```

### Restart Service
```bash
az webapp restart \
  --resource-group rmhazure_rg \
  --name rmhtitiler
```

## Testing Workflow

### 1. Test Landing Page
```bash
curl https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/
```
**Expected:** JSON with API links (all HTTPS!)

### 2. Test COG Info
```bash
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/info?url=/vsiaz/rmhazuregeobronze/05APR13082706.tif"
```
**Expected:** JSON with bounds, CRS, band metadata

### 3. Test Tile Generation
```bash
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/tiles/WebMercatorQuad/15/19665/13317?url=/vsiaz/rmhazuregeobronze/05APR13082706.tif" --output test_tile.png
```
**Expected:** PNG image file (check with `file test_tile.png`)

### 4. Test Viewer in Browser
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/viewer?url=/vsiaz/rmhazuregeobronze/05APR13082706.tif
```
**Expected:** Interactive map with satellite imagery

**If viewer doesn't work:**
- Hard refresh browser (Cmd+Shift+R / Ctrl+Shift+R)
- Open in incognito window (clears cache)
- Check browser console for errors (F12)

## Troubleshooting

### Issue: Mixed Content Errors in Browser
**Symptom:** Viewer loads but no tiles appear, browser console shows "blocked mixed content"

**Cause:** `FORWARDED_ALLOW_IPS` not set → TiTiler generates HTTP URLs

**Fix:**
```bash
az webapp config appsettings set \
  --name rmhtitiler \
  --resource-group rmhazure_rg \
  --settings FORWARDED_ALLOW_IPS=*

az webapp restart --name rmhtitiler --resource-group rmhazure_rg
```

### Issue: 404 on COG File
**Symptom:** `{"detail": "HTTP response code: 404"}`

**Causes:**
1. File doesn't exist at that path in blob storage
2. Wrong container name
3. Wrong blob name (check case sensitivity!)

**Fix:** Verify file exists:
```bash
az storage blob exists \
  --account-name rmhazuregeo \
  --container-name silver-cogs \
  --name 05APR13082706_cog_analysis.tif
```

### Issue: Authentication Errors
**Symptom:** `{"detail": "Missing AZURE_STORAGE_ACCOUNT..."}`

**Cause:** Storage account credentials not set

**Fix:** Ensure `AZURE_STORAGE_ACCOUNT` and `AZURE_STORAGE_ACCESS_KEY` are configured

### Issue: Viewer Shows Black/Gray Tiles
**Symptom:** Map loads but tiles are blank or wrong colors

**Cause:** Incorrect `rescale` parameter or band selection

**Fix:** Let TiTiler auto-detect:
```
# Remove rescale parameter from URL
/cog/viewer?url=/vsiaz/{container}/{blob}
# (no &rescale=... parameter)
```

## Performance Notes

**GDAL Environment Variables Impact:**
- `GDAL_HTTP_VERSION=2`: HTTP/2 for faster transfers
- `GDAL_HTTP_MULTIPLEX=YES`: Parallel range requests
- `VSI_CACHE=TRUE`: Caches file headers
- `GDAL_CACHEMAX=200`: 200MB in-memory cache

**Typical Performance:**
- First tile request: ~1-3 seconds (cold start)
- Subsequent tiles: ~100-300ms (cached headers)
- Viewer load time: ~2-5 seconds (includes basemap)

## Security Considerations

### Current (Development)
- ⚠️ Storage account key in environment variables
- ✅ CORS enabled for all origins (`*`)
- ✅ HTTPS enforced
- ⚠️ No authentication on endpoints

### Production Recommendations
1. **Use SAS Tokens** instead of account key
2. **Enable Azure App Service Authentication**
3. **Restrict CORS** to specific domains
4. **Implement rate limiting** via Azure Front Door
5. **Use Private Endpoints** for storage access
6. **Migrate to Managed Identity** for storage (see note below)

### Future: Managed Identity for Azure Storage

**Challenge:** GDAL's `/vsiaz/` driver only supports Azure VM IMDS (Instance Metadata Service). Azure App Service uses different endpoints (`IDENTITY_ENDPOINT` + `IDENTITY_HEADER`).

**Current Workaround:** Using storage account key

**Future Solutions:**
1. Generate SAS tokens using managed identity
2. Build custom TiTiler container with token refresh logic
3. Move to Azure Container Instance (supports VM-style IMDS)

## URL Encoding Reference

When passing COG URLs to TiTiler, URL-encode the `/vsiaz/` path:

```bash
# Raw path
/vsiaz/silver-cogs/05APR13082706_cog_analysis.tif

# URL-encoded
%2Fvsiaz%2Fsilver-cogs%2F05APR13082706_cog_analysis.tif

# Full URL
https://rmhtitiler.../cog/viewer?url=%2Fvsiaz%2Fsilver-cogs%2F05APR13082706_cog_analysis.tif
```

**Python helper:**
```python
import urllib.parse
url = "/vsiaz/silver-cogs/05APR13082706_cog_analysis.tif"
encoded = urllib.parse.quote(url, safe='')
print(f"https://rmhtitiler.../cog/viewer?url={encoded}")
```

## Related Documentation

- [TiTiler Documentation](https://developmentseed.org/titiler/)
- [GDAL Virtual File Systems](https://gdal.org/user/virtual_file_systems.html)
- [Cloud-Optimized GeoTIFF](https://www.cogeo.org/)
- [Azure Web App Container Deployment](https://learn.microsoft.com/en-us/azure/app-service/configure-custom-container)

## Migration History

**28 OCT 2025**: Initial TiTiler-PgSTAC deployment on Azure Web App
**7 NOV 2025**: ✅ **Successfully migrated to Vanilla TiTiler** with `/vsiaz/` direct access
**Performance**: Simpler, faster, no database dependency!

## Future Enhancements

- [ ] Migrate from account key to SAS token generation
- [ ] Implement managed identity for storage (requires custom token fetcher)
- [ ] Add authentication layer (Azure AD)
- [ ] Set up Redis caching for tile responses
- [ ] Configure CDN for global tile delivery
- [ ] Add custom styling API endpoints
- [ ] Implement usage analytics and monitoring

---

**Status**: ✅ **PRODUCTION READY** - Vanilla TiTiler fully operational with direct Azure Blob Storage access!
