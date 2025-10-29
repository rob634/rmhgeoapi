# PgSTAC Schema Setup Required

**Date**: 28 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: ⚠️ SETUP REQUIRED

## Current Situation

The TiTiler Web App is running **titiler-pgstac** which is STAC-only and does NOT have `/cog/` endpoints for direct COG access.

### What's Deployed:
- **Container Image**: `ghcr.io/stac-utils/titiler-pgstac:latest`
- **Type**: STAC-focused tile server (not the general-purpose TiTiler)
- **Requires**: PgSTAC schema in PostgreSQL database

### What's Missing:
- ❌ PgSTAC schema not installed in PostgreSQL
- ❌ No STAC collections created
- ❌ No STAC items ingested
- ❌ Cannot use `/cog/` endpoints (not available in titiler-pgstac)

## Error Messages

```json
{
  "detail": "schema \"pgstac\" does not exist\nLINE 1: SELECT * FROM pgstac.all_collections();\n                      ^"
}
```

This confirms the `pgstac` schema needs to be created before TiTiler can function.

## Two Paths Forward

### Option 1: Set Up PgSTAC (Recommended for Production)

**Pros:**
- ✅ Powerful STAC catalog with search capabilities
- ✅ Temporal and spatial queries
- ✅ Collection management
- ✅ Designed for large raster datasets

**Cons:**
- ❌ More complex setup
- ❌ Requires schema migration
- ❌ Need to ingest STAC items

**Steps:**
1. Install PgSTAC extension in PostgreSQL
2. Run PgSTAC schema migrations
3. Create STAC collections
4. Ingest STAC items pointing to your COGs
5. Use `/searches/`, `/collections/` endpoints

### Option 2: Redeploy with TiTiler-Core (Simple Direct COG Access)

**Pros:**
- ✅ Simple direct COG URL access
- ✅ No database setup required
- ✅ Works immediately with COG URLs
- ✅ Great for testing and simple use cases

**Cons:**
- ❌ No STAC catalog features
- ❌ No search capabilities
- ❌ Must know exact COG URLs

**Steps:**
1. Deploy `ghcr.io/developmentseed/titiler:latest` (core version)
2. Use `/cog/tiles/{z}/{x}/{y}?url={cog_url}` endpoints
3. Works with any public or accessible COG URL

## Comparison: titiler-pgstac vs titiler-core

| Feature | titiler-pgstac (current) | titiler-core |
|---------|--------------------------|--------------|
| **Direct COG URLs** | ❌ Not available | ✅ Yes via `/cog/` |
| **STAC Catalog** | ✅ Full support | ❌ No |
| **Database Required** | ✅ PostgreSQL + PgSTAC | ❌ Optional |
| **Search Capabilities** | ✅ Temporal, spatial | ❌ No |
| **Setup Complexity** | 🔴 High | 🟢 Low |
| **Use Case** | Production catalogs | Testing, simple apps |

## Recommended Approach

### Phase 1: Quick Testing (Now)
**Redeploy with titiler-core** to test COGs immediately:

```bash
# Update Web App to use titiler-core
az webapp config container set \
  --resource-group rmhazure_rg \
  --name rmhtitiler \
  --docker-custom-image-name ghcr.io/developmentseed/titiler:latest

# Restart
az webapp restart --resource-group rmhazure_rg --name rmhtitiler
```

Then test with:
```bash
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/info?url=https://rmhazuregeo.blob.core.windows.net/rmhazuregeosilver/namangan/namangan14aug2019_R1C2cog_analysis.tif"
```

### Phase 2: Production Setup (Later)
**Set up PgSTAC** for production:

1. Connect to PostgreSQL and install PgSTAC:
```sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE SCHEMA IF NOT EXISTS pgstac;
-- Run PgSTAC migration scripts
```

2. Switch back to titiler-pgstac
3. Ingest STAC items with COG references
4. Use full STAC search capabilities

## Current Status

### What's Working:
- ✅ TiTiler Web App deployed and running
- ✅ Managed identity configured
- ✅ Storage Blob Data Reader role assigned
- ✅ Environment variables set correctly
- ✅ Health endpoint responding

### What's Blocked:
- ❌ Cannot access COGs (no `/cog/` endpoints)
- ❌ Cannot use STAC features (no pgstac schema)
- ❌ Need to choose path forward

## Testing with Current Setup

Since titiler-pgstac requires STAC items, you CANNOT test with direct COG URLs. You must either:

1. **Set up PgSTAC schema** and ingest STAC items, OR
2. **Redeploy with titiler-core** for direct COG access

## Next Steps

**Decision Required:**
- Do you want to set up PgSTAC now for production use?
- Or redeploy with titiler-core for quick testing?

**For Quick Testing (Recommended):**
```bash
# Switch to titiler-core
az webapp config container set \
  --resource-group rmhazure_rg \
  --name rmhtitiler \
  --docker-custom-image-name ghcr.io/developmentseed/titiler:latest

az webapp restart --resource-group rmhazure_rg --name rmhtitiler

# Wait 30 seconds, then test
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/info?url=https://rmhazuregeo.blob.core.windows.net/rmhazuregeosilver/namangan/namangan14aug2019_R1C2cog_analysis.tif"
```

## Resources

- [PgSTAC Documentation](https://github.com/stac-utils/pgstac)
- [TiTiler-PgSTAC Docs](https://stac-utils.github.io/titiler-pgstac/)
- [TiTiler-Core Docs](https://developmentseed.org/titiler/)
- [STAC Specification](https://stacspec.org/)