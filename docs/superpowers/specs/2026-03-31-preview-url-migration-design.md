# Preview URL Migration to GeoTiler

**Date**: 31 MAR 2026
**Status**: Draft
**Scope**: rmhtitiler (GeoTiler) + rmhgeoapi (approval block only)

---

## Problem

When clients poll `GET /api/platform/status/{id}` during the approval stage of an ETL lifecycle, the response includes viewer URLs pointing at rmhgeoapi's self-hosted Leaflet viewers (`/api/interface/raster-viewer`, `/api/interface/vector-viewer`). These must change to point at GeoTiler's MapLibre GL viewers, which are the canonical viewer application.

## Decision

- GeoTiler exposes `/preview/*` routes as iframe-friendly aliases of its existing `/viewer/*` routes
- rmhgeoapi's `_build_approval_block()` exclusively targets GeoTiler `/preview/*` — no fallback to old viewers
- Old rmhgeoapi viewers remain in codebase but are not referenced by the happy path

## Design

### GeoTiler (rmhtitiler) Changes

#### New `/preview/*` Routes

Three routes aliasing existing viewers:

| Route | Mirrors | Query Params |
|---|---|---|
| `GET /preview/raster` | `/viewer/raster` | `?url=/vsiaz/container/file.tif` |
| `GET /preview/vector` | `/viewer/vector` | `?collection={postgis_table}` |
| `GET /preview/zarr` | `/viewer/zarr` | `?url=abfs://container/store.zarr&variable={var}` |

Implementation: new FastAPI router at `/geotiler/routers/preview.py` that reuses the same Jinja2 templates as the viewer router. The router renders identical pages — the only difference is the route prefix and response headers.

#### Iframe-Permissive Headers

All `/preview/*` responses set:
- `Content-Security-Policy: frame-ancestors *`
- No `X-Frame-Options` header (or explicitly `ALLOWALL`)

This allows any origin to iframe these pages. When auth gating is added later, `frame-ancestors` can be tightened to specific allowed origins.

The `/viewer/*` routes are unaffected — they retain default framing headers.

#### No Other Changes

- No visual changes to viewer templates or JavaScript
- No new templates — reuse existing `pages/viewer/{raster,vector,zarr}.html`
- No new static assets
- No new config variables

### rmhgeoapi Changes

#### Update `_build_approval_block()`

**File**: `triggers/trigger_platform_status.py` (~lines 1108-1175)

Change URL construction from local viewers to GeoTiler `/preview/*`:

| Data Type | Before | After |
|---|---|---|
| Raster | `{platform_base}/api/interface/raster-viewer?url={cog_url}&asset_id={id}` | `{titiler_base}/preview/raster?url={cog_url}` |
| Vector | `{platform_base}/api/interface/vector-viewer?collection={table}&asset_id={id}` | `{titiler_base}/preview/vector?collection={table}` |
| Zarr | `{titiler_base}/xarray/WebMercatorQuad/map.html?url={url}` | `{titiler_base}/preview/zarr?url={url}` |

- `titiler_base_url` already exists in `AppConfig` — no new configuration
- `asset_id` is dropped from the URL — not needed by pure viewer
- `embed_url` field is removed — `/preview/*` is always iframe-friendly, no toggle needed

#### No Fallback

The approval block constructs GeoTiler URLs exclusively. If GeoTiler is down, the viewer URL is still returned (it's just a URL) — the client gets a broken link, not a silent fallback to a different viewer. This follows the project's explicit-failure principle.

#### Old Viewers Untouched

`/api/interface/raster-viewer` and `/api/interface/vector-viewer` remain in rmhgeoapi. They are not deleted, not deprecated with warnings, not referenced by the approval block. They exist for potential future reuse only.

## Response Format Change

### Before
```json
{
  "approval": {
    "viewer_url": "/api/interface/raster-viewer?url=/vsiaz/silver-cogs/file.tif&asset_id=ABC123",
    "embed_url": "/api/interface/raster-viewer?url=/vsiaz/silver-cogs/file.tif&asset_id=ABC123&embed=true"
  }
}
```

### After
```json
{
  "approval": {
    "viewer_url": "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurecontainer.io/preview/raster?url=%2Fvsiaz%2Fsilver-cogs%2Ffile.tif"
  }
}
```

- `embed_url` field removed (no embed toggle — `/preview/*` is always embeddable)
- `viewer_url` is now a fully qualified URL (was previously a relative path)

## Out of Scope

- Auth gating on `/preview/*` (future work)
- Removing old rmhgeoapi viewers
- Changes to `services.*` URLs in STAC items (already point to TiTiler tile/image endpoints)
- Changes to GeoTiler viewer UI or JavaScript
- Approval workflow buttons (approve/reject) — these remain in rmhgeoapi's platform API, not in the viewer

## Files Modified

### GeoTiler (rmhtitiler)
| File | Change |
|---|---|
| `geotiler/routers/preview.py` | **New** — `/preview/*` router with iframe headers |
| `geotiler/app.py` | Mount the preview router |

### rmhgeoapi
| File | Change |
|---|---|
| `triggers/trigger_platform_status.py` | Update `_build_approval_block()` URL construction |
