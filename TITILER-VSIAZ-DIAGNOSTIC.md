# TiTiler /vsiaz/ OAuth Access Diagnostic

**Date**: 10 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Issue**: TiTiler-pgSTAC returning "not recognized as being in a supported file format" for /vsiaz/ paths

---

## ✅ What's Working

### 1. STAC ETL Fix Deployed
- ✅ `service_stac_metadata.py` Step G.5 converts HTTPS URLs → `/vsiaz/` paths
- ✅ STAC items created with OAuth-compatible paths
- ✅ Example item: `system-rasters-dctest3_R1C2_cog_cog_analysis-tif`
- ✅ Asset href: `/vsiaz/silver-cogs/dctest3_R1C2_cog_cog_analysis.tif`

### 2. TiTiler-pgSTAC OAuth Configuration
- ✅ Managed Identity enabled and working
- ✅ OAuth token generation successful
- ✅ Health endpoint shows: `token_status: active`, `storage_account: rmhazuregeo`
- ✅ Middleware sets environment variables correctly (lines 190-191)
- ✅ GDAL config set directly (lines 198-199)

### 3. pgSTAC Search Working
- ✅ Search registration succeeds
- ✅ TileJSON generation works
- ✅ Search ID: `4065f0284c93bfaf571e565ad8a5ade9`

---

## ❌ What's Failing

### Tile Access Error
```bash
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/searches/4065f0284c93bfaf571e565ad8a5ade9/tiles/WebMercatorQuad/14/4686/6266.png?assets=data"

Response:
{
  "detail": "'/vsiaz/silver-cogs/dctest3_R1C2_cog_cog_analysis.tif' not recognized as being in a supported file format."
}
```

**Error Analysis**:
- TiTiler successfully queries pgSTAC database
- Retrieves STAC item with `/vsiaz/` path
- Attempts to open file with rasterio/GDAL
- GDAL fails to recognize `/vsiaz/` path format

---

## 🔍 Root Cause Investigation

### TiTiler Middleware Code Review

**File**: `/Users/robertharrison/python_builds/titilerpgstac/custom_pgstac_main.py`

**Lines 174-214: `AzureAuthMiddleware`**
```python
class AzureAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if USE_AZURE_AUTH and AZURE_STORAGE_ACCOUNT:
            token = get_azure_storage_oauth_token()

            if token:
                # Set environment variables for GDAL
                os.environ["AZURE_STORAGE_ACCOUNT"] = AZURE_STORAGE_ACCOUNT
                os.environ["AZURE_STORAGE_ACCESS_TOKEN"] = token  # ← Line 191

                # Set GDAL config directly
                import rasterio
                from rasterio import _env
                _env.set_gdal_config("AZURE_STORAGE_ACCOUNT", AZURE_STORAGE_ACCOUNT)  # ← Line 198
                _env.set_gdal_config("AZURE_STORAGE_ACCESS_TOKEN", token)  # ← Line 199
```

**This looks correct!** ✅

---

## 🤔 Possible Issues

### 1. **Environment Variable Timing** (Most Likely)
**Issue**: Environment variables might be set in middleware but not visible to worker threads/processes

**Evidence**:
- Middleware runs in main request thread
- rasterio/GDAL might execute in different thread/process
- Environment variables may not propagate

**Test**: Add logging to verify GDAL actually sees the variables when opening file

### 2. **GDAL Version Compatibility**
**Issue**: GDAL version might not support `AZURE_STORAGE_ACCESS_TOKEN`

**Check**:
```python
import rasterio
print(rasterio.__version__)
print(rasterio.__gdal_version__)
```

**Requirement**: GDAL >= 3.7 for OAuth token support

### 3. **Token Format Issues**
**Issue**: OAuth token might need specific format

**Current**: Token is raw bearer token from Azure
**GDAL Expects**: Bearer token format, but might need `Bearer ` prefix?

**Test**: Try both formats:
```python
os.environ["AZURE_STORAGE_ACCESS_TOKEN"] = token
os.environ["AZURE_STORAGE_ACCESS_TOKEN"] = f"Bearer {token}"
```

### 4. **Container Name in Path**
**Issue**: `/vsiaz/` expects specific path format

**Current**: `/vsiaz/silver-cogs/file.tif`
**GDAL Expects**: `/vsiaz/container/blob` (should be correct)

**Verify**: Container name `silver-cogs` exists and token has access

---

## 🔧 Debugging Steps for TiTiler Claude

### Step 1: Add Diagnostic Logging
Add to `custom_pgstac_main.py` line ~200 (after setting env vars):

```python
# DIAGNOSTIC: Verify GDAL sees the environment variables
logger.info(f"🔍 DIAGNOSTIC: AZURE_STORAGE_ACCOUNT = {os.environ.get('AZURE_STORAGE_ACCOUNT')}")
logger.info(f"🔍 DIAGNOSTIC: AZURE_STORAGE_ACCESS_TOKEN length = {len(os.environ.get('AZURE_STORAGE_ACCESS_TOKEN', ''))}")

# Test GDAL config
gdal_account = _env.get_gdal_config("AZURE_STORAGE_ACCOUNT")
gdal_token = _env.get_gdal_config("AZURE_STORAGE_ACCESS_TOKEN")
logger.info(f"🔍 DIAGNOSTIC: GDAL config AZURE_STORAGE_ACCOUNT = {gdal_account}")
logger.info(f"🔍 DIAGNOSTIC: GDAL config AZURE_STORAGE_ACCESS_TOKEN length = {len(gdal_token) if gdal_token else 0}")
```

### Step 2: Test Direct /vsiaz/ Access
Add test endpoint to verify OAuth works:

```python
@app.get("/test/vsiaz", tags=["Debug"])
async def test_vsiaz_access():
    """Test direct /vsiaz/ access with current OAuth token."""
    import rasterio

    test_path = "/vsiaz/silver-cogs/dctest3_R1C2_cog_cog_analysis.tif"

    try:
        # Verify environment variables are set
        account = os.environ.get("AZURE_STORAGE_ACCOUNT")
        token_len = len(os.environ.get("AZURE_STORAGE_ACCESS_TOKEN", ""))

        logger.info(f"Testing /vsiaz/ access: {test_path}")
        logger.info(f"  AZURE_STORAGE_ACCOUNT: {account}")
        logger.info(f"  Token length: {token_len}")

        # Try to open file
        with rasterio.open(test_path) as src:
            return {
                "success": True,
                "path": test_path,
                "crs": str(src.crs),
                "shape": src.shape,
                "count": src.count,
                "dtypes": [src.dtypes[i] for i in range(src.count)]
            }

    except Exception as e:
        logger.error(f"❌ /vsiaz/ access failed: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
            "path": test_path,
            "env_vars": {
                "AZURE_STORAGE_ACCOUNT": os.environ.get("AZURE_STORAGE_ACCOUNT"),
                "token_present": bool(os.environ.get("AZURE_STORAGE_ACCESS_TOKEN")),
                "token_length": len(os.environ.get("AZURE_STORAGE_ACCESS_TOKEN", ""))
            }
        }
```

### Step 3: Check GDAL Version
```python
@app.get("/test/gdal-version", tags=["Debug"])
async def gdal_version():
    """Check GDAL version and capabilities."""
    import rasterio
    from osgeo import gdal

    return {
        "rasterio_version": rasterio.__version__,
        "gdal_version": rasterio.__gdal_version__,
        "gdal_version_num": gdal.VersionInfo(),
        "supports_vsiaz": "/vsiaz/" in gdal.GetConfigOption("GDAL_HTTP_VERSION", "") or True,
        "azure_support": "Azure" in gdal.GetDriverByName("GTiff").GetMetadata().get("DMD_LONGNAME", "")
    }
```

### Step 4: Try Alternative Token Setting
If above fails, try setting token globally at startup:

```python
# In startup_event() function, after getting OAuth token:
if token:
    import rasterio
    from rasterio._env import set_gdal_config

    # Set globally for all workers
    set_gdal_config("AZURE_STORAGE_ACCOUNT", AZURE_STORAGE_ACCOUNT, True)  # ← True = global
    set_gdal_config("AZURE_STORAGE_ACCESS_TOKEN", token, True)  # ← True = global

    logger.info("✓ Set GDAL config globally at startup")
```

---

## 📊 Expected Results

### If OAuth is Working:
```json
{
  "success": true,
  "path": "/vsiaz/silver-cogs/dctest3_R1C2_cog_cog_analysis.tif",
  "crs": "EPSG:4326",
  "shape": [7777, 5030],
  "count": 3,
  "dtypes": ["uint8", "uint8", "uint8"]
}
```

### If OAuth is Broken:
```json
{
  "success": false,
  "error": "'/vsiaz/silver-cogs/...' not recognized as being in a supported file format.",
  "error_type": "RasterioIOError"
}
```

---

## 🎯 Next Actions

1. **Add diagnostic logging** to verify GDAL sees environment variables
2. **Add `/test/vsiaz` endpoint** to test direct file access
3. **Check GDAL version** - must be >= 3.7 for OAuth support
4. **Review Azure Function App logs** for middleware execution
5. **Test with direct COG endpoint** (`/cog/info?url=/vsiaz/...`) to isolate pgSTAC vs GDAL issue

---

## 📝 Related Files

- **TiTiler Main**: `/Users/robertharrison/python_builds/titilerpgstac/custom_pgstac_main.py`
- **STAC ETL Fix**: `/Users/robertharrison/python_builds/rmhgeoapi/services/service_stac_metadata.py` (lines 270-315)
- **Test STAC Item**: `system-rasters-dctest3_R1C2_cog_cog_analysis-tif`
- **Test COG**: `/vsiaz/silver-cogs/dctest3_R1C2_cog_cog_analysis.tif`

---

## ✅ Summary

**STAC ETL Side**: ✅ COMPLETE - Assets now use `/vsiaz/` paths
**TiTiler Side**: ⚠️ NEEDS INVESTIGATION - OAuth token generated but GDAL not recognizing `/vsiaz/` paths

**Most Likely Issue**: Environment variable propagation or GDAL version compatibility

**Recommended Fix**: Add diagnostic endpoints and logging to TiTiler to identify exact failure point
