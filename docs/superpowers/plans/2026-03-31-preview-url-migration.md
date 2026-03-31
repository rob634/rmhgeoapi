# Preview URL Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Change the approval viewer URLs in `/api/platform/status/{id}` responses to point at GeoTiler's `/preview/*` endpoints instead of rmhgeoapi's self-hosted viewers.

**Architecture:** Single function edit in `trigger_platform_status.py`. The `_build_approval_block()` function currently constructs URLs against `{platform_base}/api/interface/*`. We replace those with `{titiler_base}/preview/*`, drop `asset_id` from viewer URLs, and remove `embed_url` (GeoTiler `/preview/*` is always iframe-friendly).

**Tech Stack:** Python, Azure Functions HTTP triggers

---

### Task 1: Update `_build_approval_block()` to use GeoTiler preview URLs

**Files:**
- Modify: `triggers/trigger_platform_status.py:1108-1175`

- [ ] **Step 1: Update raster approval URL construction (lines 1142-1153)**

Replace the raster block. The `titiler_base_url` is on `AppConfig` (already imported via `get_config()`). Drop `asset_id` from URL. Drop `embed_url`. Use `/preview/raster` path.

Change:
```python
    if data_type == "raster" and release.blob_path:
        from urllib.parse import quote
        # Always use direct COG URL (?url=) for approval preview.
        # STAC item doesn't exist yet — it's materialized AFTER approval.
        # TiTiler works directly from blob_path, no STAC needed.
        if release.blob_path.startswith('/vsiaz/'):
            cog_url = quote(release.blob_path, safe='')
        else:
            container = _infer_raster_container(release, None, config)
            cog_url = quote(f"/vsiaz/{container}/{release.blob_path}", safe='')
        approval["viewer_url"] = f"{platform_base}/api/interface/raster-viewer?url={cog_url}&asset_id={asset_id}"
        approval["embed_url"] = f"{platform_base}/api/interface/raster-viewer?url={cog_url}&asset_id={asset_id}&embed=true"
```

To:
```python
    if data_type == "raster" and release.blob_path:
        from urllib.parse import quote
        titiler_base = config.titiler_base_url.rstrip('/')
        if release.blob_path.startswith('/vsiaz/'):
            cog_url = quote(release.blob_path, safe='')
        else:
            container = _infer_raster_container(release, None, config)
            cog_url = quote(f"/vsiaz/{container}/{release.blob_path}", safe='')
        approval["viewer_url"] = f"{titiler_base}/preview/raster?url={cog_url}"
```

- [ ] **Step 2: Update vector approval URL construction (lines 1155-1163)**

Change:
```python
    elif data_type == "vector":
        table_names = _get_release_table_names(release.release_id)
        if table_names:
            # Use first/primary table for viewer URLs
            primary_table = table_names[0]
            approval["viewer_url"] = f"{platform_base}/api/interface/vector-viewer?collection={primary_table}&asset_id={asset_id}"
            approval["embed_url"] = f"{platform_base}/api/interface/vector-viewer?collection={primary_table}&asset_id={asset_id}&embed=true"
            if len(table_names) > 1:
                approval["all_tables"] = table_names
```

To:
```python
    elif data_type == "vector":
        table_names = _get_release_table_names(release.release_id)
        if table_names:
            titiler_base = config.titiler_base_url.rstrip('/')
            primary_table = table_names[0]
            approval["viewer_url"] = f"{titiler_base}/preview/vector?collection={primary_table}"
            if len(table_names) > 1:
                approval["all_tables"] = table_names
```

- [ ] **Step 3: Update zarr approval URL construction (lines 1165-1173)**

Change:
```python
    elif data_type == "zarr" and release.blob_path:
        from urllib.parse import quote
        # Build zarr preview URL for reviewer
        # No {variable} substitution — reviewer selects variable interactively in TiTiler map UI
        zarr_url = _build_zarr_url(release, config)
        if zarr_url:
            encoded = quote(zarr_url, safe='')
            titiler_base = config.titiler_base_url.rstrip('/')
            approval["viewer_url"] = f"{titiler_base}/xarray/WebMercatorQuad/map.html?url={encoded}&decode_times=false"
```

To:
```python
    elif data_type == "zarr" and release.blob_path:
        from urllib.parse import quote
        zarr_url = _build_zarr_url(release, config)
        if zarr_url:
            encoded = quote(zarr_url, safe='')
            titiler_base = config.titiler_base_url.rstrip('/')
            approval["viewer_url"] = f"{titiler_base}/preview/zarr?url={encoded}"
```

- [ ] **Step 4: Remove unused `platform_base` variable (line 1135)**

After the changes above, `platform_base` is only used for `approve_url` (line 1138). Keep it for that — no change needed. Verify by reading the final function.

- [ ] **Step 5: Verify the edit**

Run:
```bash
cd /Users/robertharrison/python_builds/rmhgeoapi
python -c "import ast; ast.parse(open('triggers/trigger_platform_status.py').read()); print('Syntax OK')"
```
Expected: `Syntax OK`

- [ ] **Step 6: Commit**

```bash
git add triggers/trigger_platform_status.py
git commit -m "feat: migrate approval viewer URLs to GeoTiler /preview/* endpoints"
```
