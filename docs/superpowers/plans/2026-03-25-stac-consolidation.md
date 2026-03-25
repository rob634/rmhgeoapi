# STAC Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace 3 item builders and 5 pgSTAC write paths with one canonical builder, one materialization function, and one collection builder.

**Architecture:** Three new pure-function files (`stac_item_builder.py`, `stac_collection_builder.py`, `stac_preview.py`) provide the canonical build functions. A new `materialize_to_pgstac()` method on `STACMaterializer` is the single pgSTAC write path. Existing handlers are rewired to call these, then dead code is deleted.

**Tech Stack:** Python 3.12, pytest, STAC 1.0.0 spec, pgSTAC, existing `stac_renders.build_renders()` and `PgSTACSearchRegistration`

**Spec:** `docs/superpowers/specs/2026-03-25-stac-consolidation-design.md`

**Environment:** `conda activate azgeo` before running any Python/pytest commands.

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `services/stac/stac_item_builder.py` | `build_stac_item()` — one canonical item builder (pure function) |
| `services/stac/stac_collection_builder.py` | `build_stac_collection()` — one canonical collection builder (pure function) |
| `services/stac/stac_preview.py` | `build_preview_item()` — skeleton items for TiTiler tiled preview (pure function) |
| `tests/unit/stac/__init__.py` | Test package init |
| `tests/unit/stac/test_stac_item_builder.py` | Unit tests for `build_stac_item()` |
| `tests/unit/stac/test_stac_collection_builder.py` | Unit tests for `build_stac_collection()` |
| `tests/unit/stac/test_stac_preview.py` | Unit tests for `build_preview_item()` |
| `tests/unit/stac/test_materialize_to_pgstac.py` | Unit tests for `materialize_to_pgstac()` |

### Modified Files

| File | Change |
|------|--------|
| `services/stac_materialization.py` | Add `materialize_to_pgstac()` method to `STACMaterializer` |
| `services/stac/handler_materialize_item.py` | Rewire to call `materialize_to_pgstac()` |
| `services/raster/handler_persist_app_tables.py` | Replace `_build_stac_item_json()` with `build_stac_item()` call |
| `services/raster/handler_persist_tiled.py` | Replace `_build_tile_stac_item()` with `build_stac_item()` + `build_preview_item()` |
| `services/zarr/handler_register.py` | Replace inline zarr builder with `build_stac_item()` call |

### Constants Reference (do NOT modify)

| File | What to import |
|------|---------------|
| `core/models/stac.py` | `STAC_VERSION`, `APP_PREFIX`, `STAC_EXT_PROJECTION`, `STAC_EXT_RASTER`, `STAC_EXT_RENDER`, `STAC_EXT_PROCESSING` |
| `services/stac_renders.py` | `build_renders(raster_type, band_count, dtype, band_stats)` |

---

## Phase 1: New Builders + Tests

### Task 1: `build_stac_item()` — Tests

**Files:**
- Create: `tests/unit/stac/__init__.py`
- Create: `tests/unit/stac/test_stac_item_builder.py`

- [ ] **Step 1: Create test package**

```bash
mkdir -p tests/unit/stac
touch tests/unit/stac/__init__.py
```

- [ ] **Step 2: Write failing tests**

```python
# tests/unit/stac/test_stac_item_builder.py
"""Unit tests for the canonical STAC item builder."""
import pytest


class TestBuildStacItemRequired:
    """Tests for required fields and minimal items."""

    def test_minimal_raster_item_has_required_fields(self):
        """Minimal COG item with only required params produces valid STAC."""
        from services.stac.stac_item_builder import build_stac_item

        item = build_stac_item(
            item_id="test-cog-001",
            collection_id="test-collection",
            bbox=[71.6, 40.9, 71.7, 41.0],
            asset_href="/vsiaz/silver/test.tif",
            asset_type="image/tiff; application=geotiff; profile=cloud-optimized",
        )

        assert item["type"] == "Feature"
        assert item["stac_version"] == "1.0.0"
        assert item["id"] == "test-cog-001"
        assert item["collection"] == "test-collection"
        assert item["bbox"] == [71.6, 40.9, 71.7, 41.0]
        assert item["geometry"]["type"] == "Polygon"
        assert item["links"] == []
        assert "data" in item["assets"]
        assert item["assets"]["data"]["href"] == "/vsiaz/silver/test.tif"
        assert item["assets"]["data"]["roles"] == ["data"]

    def test_sentinel_datetime_when_none_provided(self):
        """No datetime -> sentinel 0001-01-01 + geoetl:temporal_source unknown."""
        from services.stac.stac_item_builder import build_stac_item

        item = build_stac_item(
            item_id="t1", collection_id="c1",
            bbox=[0, 0, 1, 1],
            asset_href="/vsiaz/silver/t.tif",
            asset_type="image/tiff; application=geotiff; profile=cloud-optimized",
        )

        assert item["properties"]["datetime"] == "0001-01-01T00:00:00Z"
        assert item["properties"]["geoetl:temporal_source"] == "unknown"

    def test_explicit_datetime_used(self):
        """Explicit datetime is used, no sentinel flag."""
        from services.stac.stac_item_builder import build_stac_item

        item = build_stac_item(
            item_id="t1", collection_id="c1",
            bbox=[0, 0, 1, 1],
            asset_href="/vsiaz/silver/t.tif",
            asset_type="image/tiff; application=geotiff; profile=cloud-optimized",
            datetime="2025-06-15T00:00:00Z",
        )

        assert item["properties"]["datetime"] == "2025-06-15T00:00:00Z"
        assert "geoetl:temporal_source" not in item["properties"]

    def test_temporal_range_sets_datetime_to_start(self):
        """start/end datetime -> datetime=start, both range fields present."""
        from services.stac.stac_item_builder import build_stac_item

        item = build_stac_item(
            item_id="t1", collection_id="c1",
            bbox=[0, 0, 1, 1],
            asset_href="abfs://container/store.zarr",
            asset_type="application/vnd+zarr",
            start_datetime="2020-01-01T00:00:00Z",
            end_datetime="2024-12-31T00:00:00Z",
        )

        props = item["properties"]
        assert props["datetime"] == "2020-01-01T00:00:00Z"
        assert props["start_datetime"] == "2020-01-01T00:00:00Z"
        assert props["end_datetime"] == "2024-12-31T00:00:00Z"


class TestBuildStacItemProjection:
    """Tests for proj:* extension fields."""

    def test_epsg_crs_sets_proj_epsg(self):
        from services.stac.stac_item_builder import build_stac_item

        item = build_stac_item(
            item_id="t1", collection_id="c1",
            bbox=[0, 0, 1, 1],
            asset_href="/vsiaz/silver/t.tif",
            asset_type="image/tiff; application=geotiff; profile=cloud-optimized",
            crs="EPSG:4326",
        )

        assert item["properties"]["proj:epsg"] == 4326
        ext = item["stac_extensions"]
        assert any("projection" in e for e in ext)

    def test_wkt_crs_sets_proj_wkt2(self):
        from services.stac.stac_item_builder import build_stac_item

        item = build_stac_item(
            item_id="t1", collection_id="c1",
            bbox=[0, 0, 1, 1],
            asset_href="/vsiaz/silver/t.tif",
            asset_type="image/tiff; application=geotiff; profile=cloud-optimized",
            crs="PROJCS[\"WGS 84\"]",
        )

        assert "proj:wkt2" in item["properties"]
        assert "proj:epsg" not in item["properties"]

    def test_no_crs_means_no_projection_extension(self):
        from services.stac.stac_item_builder import build_stac_item

        item = build_stac_item(
            item_id="t1", collection_id="c1",
            bbox=[0, 0, 1, 1],
            asset_href="/vsiaz/silver/t.tif",
            asset_type="image/tiff; application=geotiff; profile=cloud-optimized",
        )

        assert "proj:epsg" not in item["properties"]
        assert not any("projection" in e for e in item.get("stac_extensions", []))


class TestBuildStacItemExtensions:
    """Tests for stac_extensions computed from provided fields."""

    def test_extensions_include_raster_when_bands_provided(self):
        from services.stac.stac_item_builder import build_stac_item

        item = build_stac_item(
            item_id="t1", collection_id="c1",
            bbox=[0, 0, 1, 1],
            asset_href="/vsiaz/silver/t.tif",
            asset_type="image/tiff; application=geotiff; profile=cloud-optimized",
            raster_bands=[{"data_type": "uint8", "statistics": {"minimum": 0, "maximum": 255}}],
        )

        assert any("raster" in e for e in item["stac_extensions"])
        assert item["assets"]["data"]["raster:bands"] == item["assets"]["data"]["raster:bands"]

    def test_extensions_minimal_when_nothing_optional(self):
        from services.stac.stac_item_builder import build_stac_item

        item = build_stac_item(
            item_id="t1", collection_id="c1",
            bbox=[0, 0, 1, 1],
            asset_href="/vsiaz/silver/t.tif",
            asset_type="image/tiff; application=geotiff; profile=cloud-optimized",
        )

        # No CRS, no bands, no renders -> only processing extension
        # (processing:lineage is always present in cached items)
        ext = item["stac_extensions"]
        assert len(ext) == 1
        assert "processing" in ext[0]


class TestBuildStacItemZarr:
    """Tests for zarr-specific items."""

    def test_zarr_item_uses_zarr_store_asset_key(self):
        from services.stac.stac_item_builder import build_stac_item

        item = build_stac_item(
            item_id="zarr-001", collection_id="zarr-coll",
            bbox=[-180, -90, 180, 90],
            asset_href="abfs://container/store.zarr",
            asset_type="application/vnd+zarr",
            asset_key="zarr-store",
            zarr_variables=["temperature", "precipitation"],
            zarr_dimensions={"time": 365, "lat": 720, "lon": 1440},
        )

        assert "zarr-store" in item["assets"]
        assert "data" not in item["assets"]
        props = item["properties"]
        assert props["zarr:variables"] == ["temperature", "precipitation"]
        assert props["zarr:dimensions"] == {"time": 365, "lat": 720, "lon": 1440}


class TestBuildStacItemPlatformRefs:
    """Tests for ddh:* and geo:* properties."""

    def test_ddh_properties_included_when_provided(self):
        from services.stac.stac_item_builder import build_stac_item

        item = build_stac_item(
            item_id="t1", collection_id="c1",
            bbox=[0, 0, 1, 1],
            asset_href="/vsiaz/silver/t.tif",
            asset_type="image/tiff; application=geotiff; profile=cloud-optimized",
            dataset_id="ds-floods",
            resource_id="res-jakarta",
            version_id="v1.0",
        )

        props = item["properties"]
        assert props["ddh:dataset_id"] == "ds-floods"
        assert props["ddh:resource_id"] == "res-jakarta"
        assert props["ddh:version_id"] == "v1.0"

    def test_geo_properties_included_when_provided(self):
        from services.stac.stac_item_builder import build_stac_item

        item = build_stac_item(
            item_id="t1", collection_id="c1",
            bbox=[0, 0, 1, 1],
            asset_href="/vsiaz/silver/t.tif",
            asset_type="image/tiff; application=geotiff; profile=cloud-optimized",
            iso3_codes=["IDN"],
            primary_iso3="IDN",
            country_names=["Indonesia"],
        )

        props = item["properties"]
        assert props["geo:iso3"] == ["IDN"]
        assert props["geo:primary_iso3"] == "IDN"
        assert props["geo:countries"] == ["Indonesia"]

    def test_no_ddh_or_geo_when_not_provided(self):
        from services.stac.stac_item_builder import build_stac_item

        item = build_stac_item(
            item_id="t1", collection_id="c1",
            bbox=[0, 0, 1, 1],
            asset_href="/vsiaz/silver/t.tif",
            asset_type="image/tiff; application=geotiff; profile=cloud-optimized",
        )

        props = item["properties"]
        assert not any(k.startswith("ddh:") for k in props)
        assert not any(k.startswith("geo:") for k in props)


class TestBuildStacItemProvenance:
    """Tests for geoetl:* internal provenance properties."""

    def test_provenance_properties_included(self):
        from services.stac.stac_item_builder import build_stac_item

        item = build_stac_item(
            item_id="t1", collection_id="c1",
            bbox=[0, 0, 1, 1],
            asset_href="/vsiaz/silver/t.tif",
            asset_type="image/tiff; application=geotiff; profile=cloud-optimized",
            job_id="job-abc123",
            epoch=5,
            detected_type="dem",
        )

        props = item["properties"]
        assert props["geoetl:job_id"] == "job-abc123"
        assert props["geoetl:epoch"] == 5
        assert props["geoetl:managed_by"] == "geoetl"
        assert props["geoetl:raster_type"] == "dem"
        assert "processing:lineage" in props


class TestBuildStacItemTitle:
    """Tests for optional title."""

    def test_title_included_when_provided(self):
        from services.stac.stac_item_builder import build_stac_item

        item = build_stac_item(
            item_id="t1", collection_id="c1",
            bbox=[0, 0, 1, 1],
            asset_href="/vsiaz/silver/t.tif",
            asset_type="image/tiff; application=geotiff; profile=cloud-optimized",
            title="Jakarta Flood DEM v1.0",
        )

        assert item["properties"]["title"] == "Jakarta Flood DEM v1.0"

    def test_no_title_when_not_provided(self):
        from services.stac.stac_item_builder import build_stac_item

        item = build_stac_item(
            item_id="t1", collection_id="c1",
            bbox=[0, 0, 1, 1],
            asset_href="/vsiaz/silver/t.tif",
            asset_type="image/tiff; application=geotiff; profile=cloud-optimized",
        )

        assert "title" not in item["properties"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `conda run -n azgeo pytest tests/unit/stac/test_stac_item_builder.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.stac.stac_item_builder'`

- [ ] **Step 4: Commit test file**

```bash
git add tests/unit/stac/
git commit -m "test: add failing tests for build_stac_item canonical builder"
```

---

### Task 2: `build_stac_item()` — Implementation

**Files:**
- Create: `services/stac/stac_item_builder.py`

- [ ] **Step 1: Implement `build_stac_item()`**

```python
# services/stac/stac_item_builder.py
"""
Canonical STAC Item Builder.

One function builds all STAC items — raster (single COG, tiled), zarr.
Pure function: no I/O, no side effects. Dict in, dict out.

The output is cached in cog_metadata.stac_item_json or zarr_metadata.stac_item_json,
then materialized to pgSTAC by STACMaterializer.materialize_to_pgstac().
"""
from typing import Any, Dict, List, Optional


# Sentinel datetime for items with unknown temporal context.
# 0001-01-01 is unambiguously fake (1970 could be real for digitized imagery).
_SENTINEL_DATETIME = "0001-01-01T00:00:00Z"


def build_stac_item(
    # === Identity (required) ===
    item_id: str,
    collection_id: str,
    # === Spatial (required) ===
    bbox: List[float],
    # === Access (required) ===
    asset_href: str,
    asset_type: str,
    asset_roles: Optional[List[str]] = None,
    asset_key: str = "data",
    # === Temporal (optional) ===
    datetime: Optional[str] = None,
    start_datetime: Optional[str] = None,
    end_datetime: Optional[str] = None,
    # === Projection (optional) ===
    crs: Optional[str] = None,
    transform: Optional[list] = None,
    # === Raster metadata (optional) ===
    raster_bands: Optional[list] = None,
    detected_type: Optional[str] = None,
    band_count: Optional[int] = None,
    data_type: Optional[str] = None,
    # === Platform refs (optional) ===
    dataset_id: Optional[str] = None,
    resource_id: Optional[str] = None,
    version_id: Optional[str] = None,
    # === Geographic attribution (optional) ===
    iso3_codes: Optional[List[str]] = None,
    primary_iso3: Optional[str] = None,
    country_names: Optional[List[str]] = None,
    # === Zarr-specific (optional) ===
    zarr_variables: Optional[List[str]] = None,
    zarr_dimensions: Optional[dict] = None,
    # === Display (optional) ===
    title: Optional[str] = None,
    # === Provenance (internal, stripped at materialization) ===
    job_id: Optional[str] = None,
    epoch: int = 5,
) -> Dict[str, Any]:
    """
    Build a canonical STAC 1.0.0 Item dict.

    Pure function — no I/O, no side effects. All STAC items (raster single COG,
    raster tile, zarr) are built by this function to ensure structural consistency.

    Returns a dict ready for caching in cog_metadata.stac_item_json or
    zarr_metadata.stac_item_json.
    """
    from core.models.stac import (
        STAC_VERSION,
        APP_PREFIX,
        STAC_EXT_PROJECTION,
        STAC_EXT_RASTER,
        STAC_EXT_RENDER,
        STAC_EXT_PROCESSING,
    )

    if asset_roles is None:
        asset_roles = ["data"]

    # --- Geometry (computed from bbox) ---
    minx, miny, maxx, maxy = bbox[0], bbox[1], bbox[2], bbox[3]
    geometry = {
        "type": "Polygon",
        "coordinates": [[
            [minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy], [minx, miny],
        ]],
    }

    # --- Temporal ---
    properties: Dict[str, Any] = {}

    if start_datetime and end_datetime:
        properties["datetime"] = start_datetime
        properties["start_datetime"] = start_datetime
        properties["end_datetime"] = end_datetime
    elif datetime:
        properties["datetime"] = datetime
    else:
        properties["datetime"] = _SENTINEL_DATETIME
        properties[f"{APP_PREFIX}:temporal_source"] = "unknown"

    # --- Title ---
    if title:
        properties["title"] = title

    # --- Projection ---
    has_projection = False
    if crs:
        if crs.startswith("EPSG:"):
            try:
                properties["proj:epsg"] = int(crs.replace("EPSG:", ""))
                has_projection = True
            except ValueError:
                pass
        else:
            properties["proj:wkt2"] = crs
            has_projection = True
    if transform:
        properties["proj:transform"] = transform
        has_projection = True

    # --- Renders (raster only) ---
    renders = None
    if detected_type and band_count and data_type:
        renders = _compute_renders(
            detected_type=detected_type,
            band_count=band_count,
            data_type=data_type,
            raster_bands=raster_bands,
        )
        if renders:
            properties["renders"] = renders

    # --- Provenance (geoetl:* — stripped at materialization) ---
    properties[f"{APP_PREFIX}:managed_by"] = APP_PREFIX
    properties[f"{APP_PREFIX}:epoch"] = epoch
    properties["processing:lineage"] = f"Processed by {APP_PREFIX} epoch {epoch}"
    if job_id:
        properties[f"{APP_PREFIX}:job_id"] = job_id
    if detected_type:
        properties[f"{APP_PREFIX}:raster_type"] = detected_type

    # --- Platform refs (ddh:*) ---
    if dataset_id:
        properties["ddh:dataset_id"] = dataset_id
    if resource_id:
        properties["ddh:resource_id"] = resource_id
    if version_id:
        properties["ddh:version_id"] = version_id

    # --- Geographic attribution (geo:*) ---
    if iso3_codes:
        properties["geo:iso3"] = iso3_codes
    if primary_iso3:
        properties["geo:primary_iso3"] = primary_iso3
    if country_names:
        properties["geo:countries"] = country_names

    # --- Zarr-specific ---
    if zarr_variables:
        properties["zarr:variables"] = zarr_variables
    if zarr_dimensions:
        properties["zarr:dimensions"] = zarr_dimensions

    # --- Extensions (computed from what's present) ---
    extensions = []
    if has_projection:
        extensions.append(STAC_EXT_PROJECTION)
    if raster_bands:
        extensions.append(STAC_EXT_RASTER)
    if renders:
        extensions.append(STAC_EXT_RENDER)
    # processing:lineage is always present but stripped at materialization;
    # include extension so cached item is self-describing
    extensions.append(STAC_EXT_PROCESSING)

    # --- Asset ---
    asset: Dict[str, Any] = {
        "href": asset_href,
        "type": asset_type,
        "roles": asset_roles,
    }
    if raster_bands:
        asset["raster:bands"] = raster_bands

    return {
        "type": "Feature",
        "stac_version": STAC_VERSION,
        "stac_extensions": extensions,
        "id": item_id,
        "geometry": geometry,
        "bbox": list(bbox),
        "properties": properties,
        "collection": collection_id,
        "links": [],
        "assets": {asset_key: asset},
    }


def _compute_renders(
    detected_type: str,
    band_count: int,
    data_type: str,
    raster_bands: Optional[list],
) -> Optional[Dict[str, Any]]:
    """Delegate to stac_renders.build_renders() with format conversion."""
    from services.stac_renders import build_renders

    band_stats = None
    if raster_bands:
        band_stats = []
        for rb in raster_bands:
            stats = rb.get("statistics", {})
            band_stats.append({
                "min": stats.get("min"),
                "max": stats.get("max"),
                "mean": stats.get("mean"),
                "stddev": stats.get("stddev"),
            })

    return build_renders(
        raster_type=detected_type,
        band_count=band_count,
        dtype=data_type,
        band_stats=band_stats,
    )
```

- [ ] **Step 2: Run tests**

Run: `conda run -n azgeo pytest tests/unit/stac/test_stac_item_builder.py -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add services/stac/stac_item_builder.py
git commit -m "feat: add build_stac_item canonical builder"
```

---

### Task 3: `build_stac_collection()` — Tests + Implementation

**Files:**
- Create: `tests/unit/stac/test_stac_collection_builder.py`
- Create: `services/stac/stac_collection_builder.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/stac/test_stac_collection_builder.py
"""Unit tests for the canonical STAC collection builder."""
import pytest


class TestBuildStacCollection:

    def test_minimal_collection_has_required_fields(self):
        from services.stac.stac_collection_builder import build_stac_collection

        coll = build_stac_collection(collection_id="test-coll")

        assert coll["type"] == "Collection"
        assert coll["id"] == "test-coll"
        assert coll["stac_version"] == "1.0.0"
        assert coll["license"] == "proprietary"
        assert coll["links"] == []
        assert coll["stac_extensions"] == []
        assert "extent" in coll
        assert coll["extent"]["spatial"]["bbox"] == [[-180, -90, 180, 90]]

    def test_custom_bbox_and_description(self):
        from services.stac.stac_collection_builder import build_stac_collection

        coll = build_stac_collection(
            collection_id="floods",
            bbox=[71.6, 40.9, 71.7, 41.0],
            description="Flood data collection",
        )

        assert coll["extent"]["spatial"]["bbox"] == [[71.6, 40.9, 71.7, 41.0]]
        assert coll["description"] == "Flood data collection"

    def test_temporal_extent(self):
        from services.stac.stac_collection_builder import build_stac_collection

        coll = build_stac_collection(
            collection_id="c1",
            temporal_start="2020-01-01T00:00:00Z",
            temporal_end="2024-12-31T00:00:00Z",
        )

        interval = coll["extent"]["temporal"]["interval"]
        assert interval == [["2020-01-01T00:00:00Z", "2024-12-31T00:00:00Z"]]

    def test_geo_attribution_included(self):
        from services.stac.stac_collection_builder import build_stac_collection

        coll = build_stac_collection(
            collection_id="c1",
            iso3_codes=["IDN"],
            primary_iso3="IDN",
            country_names=["Indonesia"],
        )

        assert coll["geo:iso3"] == ["IDN"]
        assert coll["geo:primary_iso3"] == "IDN"
        assert coll["geo:countries"] == ["Indonesia"]

    def test_no_geo_when_not_provided(self):
        from services.stac.stac_collection_builder import build_stac_collection

        coll = build_stac_collection(collection_id="c1")

        assert "geo:iso3" not in coll
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n azgeo pytest tests/unit/stac/test_stac_collection_builder.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `build_stac_collection()`**

```python
# services/stac/stac_collection_builder.py
"""
Canonical STAC Collection Builder.

One function builds all STAC collections. Pure function: no I/O, no side effects.
Replaces build_raster_stac_collection() and pystac.Collection usage.
"""
from typing import Any, Dict, List, Optional

from core.models.stac import STAC_VERSION


def build_stac_collection(
    collection_id: str,
    bbox: Optional[List[float]] = None,
    temporal_start: Optional[str] = None,
    temporal_end: Optional[str] = None,
    description: Optional[str] = None,
    license: str = "proprietary",
    iso3_codes: Optional[List[str]] = None,
    primary_iso3: Optional[str] = None,
    country_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Build a canonical STAC 1.0.0 Collection dict.

    Pure function — no I/O. Returns a dict ready for
    PgStacRepository.insert_collection().
    """
    if bbox is None:
        bbox = [-180, -90, 180, 90]

    collection: Dict[str, Any] = {
        "type": "Collection",
        "id": collection_id,
        "stac_version": STAC_VERSION,
        "description": description or f"Collection: {collection_id}",
        "links": [],
        "license": license,
        "extent": {
            "spatial": {"bbox": [bbox]},
            "temporal": {"interval": [[temporal_start, temporal_end]]},
        },
        "stac_extensions": [],
    }

    if iso3_codes:
        collection["geo:iso3"] = iso3_codes
    if primary_iso3:
        collection["geo:primary_iso3"] = primary_iso3
    if country_names:
        collection["geo:countries"] = country_names

    return collection
```

- [ ] **Step 4: Run tests**

Run: `conda run -n azgeo pytest tests/unit/stac/test_stac_collection_builder.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add tests/unit/stac/test_stac_collection_builder.py services/stac/stac_collection_builder.py
git commit -m "feat: add build_stac_collection canonical builder"
```

---

### Task 4: `build_preview_item()` — Tests + Implementation

**Files:**
- Create: `tests/unit/stac/test_stac_preview.py`
- Create: `services/stac/stac_preview.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/stac/test_stac_preview.py
"""Unit tests for the STAC preview item builder (tiled TiTiler skeleton)."""
import pytest


class TestBuildPreviewItem:

    def test_preview_item_is_minimal(self):
        from services.stac.stac_preview import build_preview_item

        item = build_preview_item(
            item_id="tile-R0C0",
            collection_id="tiled-coll",
            bbox=[71.6, 40.9, 71.7, 41.0],
            asset_href="/vsiaz/silver/tile_R0C0.tif",
        )

        assert item["type"] == "Feature"
        assert item["stac_version"] == "1.0.0"
        assert item["stac_extensions"] == []
        assert item["id"] == "tile-R0C0"
        assert item["collection"] == "tiled-coll"
        assert item["bbox"] == [71.6, 40.9, 71.7, 41.0]
        assert item["geometry"]["type"] == "Polygon"
        assert item["links"] == []

        # Only datetime in properties — nothing else
        assert item["properties"]["datetime"] == "0001-01-01T00:00:00Z"
        assert len(item["properties"]) == 1

        # Single asset
        assert "data" in item["assets"]
        assert item["assets"]["data"]["href"] == "/vsiaz/silver/tile_R0C0.tif"
        assert item["assets"]["data"]["roles"] == ["data"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n azgeo pytest tests/unit/stac/test_stac_preview.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `build_preview_item()`**

```python
# services/stac/stac_preview.py
"""
STAC Preview Item Builder.

Builds minimal skeleton items for TiTiler tiled mosaic preview.
These are inserted into pgSTAC at processing time (before approval)
so TiTiler can render the mosaic immediately.

Full items replace these at approval time via materialize_to_pgstac().
"""
from typing import Any, Dict, List

from core.models.stac import STAC_VERSION

_SENTINEL_DATETIME = "0001-01-01T00:00:00Z"
_COG_MEDIA_TYPE = "image/tiff; application=geotiff; profile=cloud-optimized"


def build_preview_item(
    item_id: str,
    collection_id: str,
    bbox: List[float],
    asset_href: str,
    asset_type: str = _COG_MEDIA_TYPE,
) -> Dict[str, Any]:
    """
    Build a minimal STAC item for TiTiler tiled preview.

    Contains only what TiTiler needs: geometry, bbox, asset href.
    No extensions, no metadata, no provenance.
    """
    minx, miny, maxx, maxy = bbox[0], bbox[1], bbox[2], bbox[3]

    return {
        "type": "Feature",
        "stac_version": STAC_VERSION,
        "stac_extensions": [],
        "id": item_id,
        "collection": collection_id,
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy], [minx, miny],
            ]],
        },
        "bbox": list(bbox),
        "properties": {
            "datetime": _SENTINEL_DATETIME,
        },
        "assets": {
            "data": {
                "href": asset_href,
                "type": asset_type,
                "roles": ["data"],
            },
        },
        "links": [],
    }
```

- [ ] **Step 4: Run tests**

Run: `conda run -n azgeo pytest tests/unit/stac/test_stac_preview.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add tests/unit/stac/test_stac_preview.py services/stac/stac_preview.py
git commit -m "feat: add build_preview_item for tiled TiTiler skeleton"
```

---

### Task 5: `materialize_to_pgstac()` — Tests + Implementation

**Files:**
- Create: `tests/unit/stac/test_materialize_to_pgstac.py`
- Modify: `services/stac_materialization.py` — add `materialize_to_pgstac()` method

- [ ] **Step 1: Write failing tests**

These tests mock the pgSTAC repository to avoid DB dependency. They verify the sanitization, stamping, and TiTiler injection logic.

```python
# tests/unit/stac/test_materialize_to_pgstac.py
"""Unit tests for STACMaterializer.materialize_to_pgstac()."""
import pytest
from unittest.mock import MagicMock, patch


def _sample_cached_item():
    """A cached stac_item_json as it would exist in cog_metadata."""
    return {
        "type": "Feature",
        "stac_version": "1.0.0",
        "stac_extensions": [
            "https://stac-extensions.github.io/projection/v1.0.0/schema.json",
            "https://stac-extensions.github.io/processing/v1.2.0/schema.json",
        ],
        "id": "cog-001",
        "collection": "test-coll",
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
        "bbox": [0, 0, 1, 1],
        "properties": {
            "datetime": "0001-01-01T00:00:00Z",
            "geoetl:job_id": "job-123",
            "geoetl:managed_by": "geoetl",
            "geoetl:epoch": 5,
            "geoetl:raster_type": "dem",
            "geoetl:temporal_source": "unknown",
            "processing:lineage": "Processed by geoetl epoch 5",
            "proj:epsg": 4326,
        },
        "assets": {"data": {"href": "/vsiaz/silver/test.tif", "type": "image/tiff", "roles": ["data"]}},
        "links": [],
    }


class TestMaterializeToPgstac:

    @patch("services.stac_materialization.STACMaterializer._inject_titiler_urls")
    def test_sanitizes_geoetl_properties(self, mock_inject):
        from services.stac_materialization import STACMaterializer

        m = STACMaterializer()
        m._pgstac = MagicMock()
        m._pgstac.get_collection.return_value = {"id": "test-coll"}
        m._pgstac.insert_item.return_value = "pgstac-id-1"

        result = m.materialize_to_pgstac(
            stac_item_json=_sample_cached_item(),
            collection_id="test-coll",
            blob_path="silver/test.tif",
        )

        assert result["success"] is True
        # Verify the item passed to insert_item has no geoetl:* properties
        call_args = m._pgstac.insert_item.call_args
        inserted_item = call_args[0][0]
        props = inserted_item["properties"]
        assert not any(k.startswith("geoetl:") for k in props)
        assert not any(k.startswith("processing:") for k in props)
        # proj:epsg should survive (not internal)
        assert props["proj:epsg"] == 4326

    @patch("services.stac_materialization.STACMaterializer._inject_titiler_urls")
    def test_stamps_approval_properties(self, mock_inject):
        from services.stac_materialization import STACMaterializer

        m = STACMaterializer()
        m._pgstac = MagicMock()
        m._pgstac.get_collection.return_value = {"id": "test-coll"}
        m._pgstac.insert_item.return_value = "pgstac-id-1"

        result = m.materialize_to_pgstac(
            stac_item_json=_sample_cached_item(),
            collection_id="test-coll",
            approved_by="reviewer@wb.org",
            approved_at="2026-03-25T12:00:00Z",
            access_level="public",
            version_id="v1.0",
        )

        call_args = m._pgstac.insert_item.call_args
        inserted_item = call_args[0][0]
        props = inserted_item["properties"]
        assert props["ddh:approved_by"] == "reviewer@wb.org"
        assert props["ddh:approved_at"] == "2026-03-25T12:00:00Z"
        assert props["ddh:access_level"] == "public"
        assert props["ddh:version_id"] == "v1.0"

    @patch("services.stac_materialization.STACMaterializer._inject_titiler_urls")
    def test_does_not_mutate_input(self, mock_inject):
        from services.stac_materialization import STACMaterializer

        m = STACMaterializer()
        m._pgstac = MagicMock()
        m._pgstac.get_collection.return_value = {"id": "test-coll"}
        m._pgstac.insert_item.return_value = "pgstac-id-1"

        original = _sample_cached_item()
        original_props_keys = set(original["properties"].keys())

        m.materialize_to_pgstac(
            stac_item_json=original,
            collection_id="test-coll",
        )

        # Original should be untouched
        assert set(original["properties"].keys()) == original_props_keys

    @patch("services.stac_materialization.STACMaterializer._inject_titiler_urls")
    def test_auto_creates_collection_if_missing(self, mock_inject):
        from services.stac_materialization import STACMaterializer

        m = STACMaterializer()
        m._pgstac = MagicMock()
        m._pgstac.get_collection.return_value = None  # collection doesn't exist
        m._pgstac.insert_item.return_value = "pgstac-id-1"
        m._pgstac.insert_collection = MagicMock()

        m.materialize_to_pgstac(
            stac_item_json=_sample_cached_item(),
            collection_id="new-coll",
        )

        # Should have called insert_collection
        assert m._pgstac.insert_collection.called
        coll_dict = m._pgstac.insert_collection.call_args[0][0]
        assert coll_dict["id"] == "new-coll"

    @patch("services.stac_materialization.STACMaterializer._inject_titiler_urls")
    def test_calls_upsert_item(self, mock_inject):
        from services.stac_materialization import STACMaterializer

        m = STACMaterializer()
        m._pgstac = MagicMock()
        m._pgstac.get_collection.return_value = {"id": "test-coll"}
        m._pgstac.insert_item.return_value = "pgstac-id-1"

        result = m.materialize_to_pgstac(
            stac_item_json=_sample_cached_item(),
            collection_id="test-coll",
        )

        assert m._pgstac.insert_item.called
        assert result["success"] is True
        assert result["pgstac_id"] == "pgstac-id-1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n azgeo pytest tests/unit/stac/test_materialize_to_pgstac.py -v`
Expected: FAIL — `AttributeError: 'STACMaterializer' object has no attribute 'materialize_to_pgstac'`

- [ ] **Step 3: Add `materialize_to_pgstac()` to `STACMaterializer`**

Add the following method to the `STACMaterializer` class in `services/stac_materialization.py`, after the `sanitize_item_properties()` method (after line 126):

```python
    def materialize_to_pgstac(
        self,
        stac_item_json: dict,
        collection_id: str,
        blob_path: Optional[str] = None,
        zarr_prefix: Optional[str] = None,
        approved_by: Optional[str] = None,
        approved_at: Optional[str] = None,
        access_level: Optional[str] = None,
        version_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Single pgSTAC write path for all STAC items.

        Steps (always in this order):
        1. Copy item dict (no mutation of cached source)
        2. Sanitize (strip geoetl:*, processing:*)
        3. Stamp ddh:approved_* if approval params provided
        4. Inject TiTiler URLs if blob_path or zarr_prefix provided
        5. Ensure collection exists (auto-create if missing)
        6. upsert_item() — always upsert, never create

        Args:
            stac_item_json: Cached item dict from cog_metadata/zarr_metadata
            collection_id: Target pgSTAC collection
            blob_path: Silver blob path for COG TiTiler URL injection
            zarr_prefix: Zarr store prefix for xarray URL injection
            approved_by: Reviewer name (approval flow only)
            approved_at: ISO8601 approval timestamp (approval flow only)
            access_level: "public" or "ouo" (approval flow only)
            version_id: DDH version ID (approval flow only)

        Returns:
            {"success": True, "pgstac_id": str} or {"success": False, "error": str}
        """
        import copy

        try:
            # Step 1: Copy
            item = copy.deepcopy(stac_item_json)
            item["collection"] = collection_id

            # Step 2: Sanitize
            self.sanitize_item_properties(item)

            # Step 3: Stamp approval properties
            if approved_by or approved_at or access_level or version_id:
                props = item.setdefault("properties", {})
                if approved_by:
                    props["ddh:approved_by"] = approved_by
                if approved_at:
                    props["ddh:approved_at"] = approved_at
                if access_level:
                    props["ddh:access_level"] = access_level
                if version_id:
                    props["ddh:version_id"] = version_id

            # Step 4: Inject TiTiler URLs
            if blob_path:
                self._inject_titiler_urls(item, blob_path)
            elif zarr_prefix:
                self._inject_xarray_urls(item, zarr_prefix)

            # Step 5: Ensure collection exists
            existing = self.pgstac.get_collection(collection_id)
            if not existing:
                from services.stac.stac_collection_builder import build_stac_collection
                bbox = item.get("bbox", [-180, -90, 180, 90])
                coll_dict = build_stac_collection(
                    collection_id=collection_id,
                    bbox=bbox,
                )
                self.pgstac.insert_collection(coll_dict)
                logger.info("materialize_to_pgstac: auto-created collection %s", collection_id)

            # Step 6: Upsert
            pgstac_id = self.pgstac.insert_item(item, collection_id)

            logger.info("materialize_to_pgstac: %s -> collection %s", item.get("id"), collection_id)

            return {"success": True, "pgstac_id": pgstac_id}

        except Exception as exc:
            logger.error("materialize_to_pgstac failed: %s", exc, exc_info=True)
            return {"success": False, "error": str(exc)}
```

- [ ] **Step 4: Run tests**

Run: `conda run -n azgeo pytest tests/unit/stac/test_materialize_to_pgstac.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run all STAC tests together**

Run: `conda run -n azgeo pytest tests/unit/stac/ -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add tests/unit/stac/test_materialize_to_pgstac.py services/stac_materialization.py
git commit -m "feat: add materialize_to_pgstac single write path"
```

---

## Phase 2: Wire Up DAG Handlers (Epoch 5)

### Task 6: Rewire `handler_persist_app_tables.py`

**Files:**
- Modify: `services/raster/handler_persist_app_tables.py`

**Context:** This file currently has `_build_stac_item_json()` (lines 57-193) and `_build_renders_for_stac()` (lines 196-228). Both are replaced by calling `build_stac_item()`.

- [ ] **Step 1: Read current handler entry point to understand how it calls the old builder**

Read: `services/raster/handler_persist_app_tables.py` lines 235-400 (the `raster_persist_app_tables()` function) to find where `_build_stac_item_json()` is called. Note the exact parameter mappings.

- [ ] **Step 2: Replace the `_build_stac_item_json()` call with `build_stac_item()`**

In the handler function `raster_persist_app_tables()`, find the call to `_build_stac_item_json()` and replace it with:

```python
from services.stac.stac_item_builder import build_stac_item

stac_item_json = build_stac_item(
    item_id=cog_id,
    collection_id=collection_id,
    bbox=bounds_4326,
    asset_href=cog_url,
    asset_type="image/tiff; application=geotiff; profile=cloud-optimized",
    crs=crs,
    transform=transform,
    raster_bands=raster_bands,
    detected_type=detected_type,
    band_count=band_count,
    data_type=data_type,
    job_id=job_id,
    epoch=5,
)
```

- [ ] **Step 3: Delete `_build_stac_item_json()` and `_build_renders_for_stac()` functions**

Remove lines 57-228 (the two old private functions) and the `_TEMPORAL_UNKNOWN` constant.

- [ ] **Step 4: Run existing tests to verify nothing breaks**

Run: `conda run -n azgeo pytest tests/ -v --tb=short`
Expected: ALL PASS (no existing tests depend on the deleted private functions)

- [ ] **Step 5: Commit**

```bash
git add services/raster/handler_persist_app_tables.py
git commit -m "refactor: handler_persist_app_tables uses build_stac_item"
```

---

### Task 7: Rewire `handler_persist_tiled.py`

**Files:**
- Modify: `services/raster/handler_persist_tiled.py`

**Context:** This file has `_build_tile_stac_item()` (lines 199-239) which produces a skeletal item. After consolidation: the **cached** item uses `build_stac_item()` (full metadata), the **preview** item uses `build_preview_item()` (skeleton for pgSTAC).

- [ ] **Step 1: Read the handler to understand how `_build_tile_stac_item()` is called**

Read: `services/raster/handler_persist_tiled.py` — find the call site and understand what params are available.

- [ ] **Step 2: Replace the call**

Where `_build_tile_stac_item()` was called for caching to `cog_metadata.stac_item_json`, replace with:

```python
from services.stac.stac_item_builder import build_stac_item

stac_item_json = build_stac_item(
    item_id=item_id,
    collection_id=collection_id,
    bbox=bounds_4326,
    asset_href=cog_url,
    asset_type="image/tiff; application=geotiff; profile=cloud-optimized",
    crs=crs,
    transform=transform,
    raster_bands=raster_bands,
    detected_type=detected_type,
    band_count=band_count,
    data_type=data_type,
    job_id=job_id,
    epoch=5,
)
```

Where a skeleton is inserted directly into pgSTAC for preview, use:

```python
from services.stac.stac_preview import build_preview_item

preview_item = build_preview_item(
    item_id=item_id,
    collection_id=collection_id,
    bbox=bounds_4326,
    asset_href=cog_url,
)
```

- [ ] **Step 3: Delete `_build_tile_stac_item()` function**

- [ ] **Step 4: Run tests**

Run: `conda run -n azgeo pytest tests/ -v --tb=short`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add services/raster/handler_persist_tiled.py
git commit -m "refactor: handler_persist_tiled uses build_stac_item + build_preview_item"
```

---

### Task 8: Rewire `handler_materialize_item.py`

**Files:**
- Modify: `services/stac/handler_materialize_item.py`

**Context:** This handler currently does sanitization and TiTiler injection inline (lines 60-165). Replace the inline logic with a single call to `STACMaterializer.materialize_to_pgstac()`.

- [ ] **Step 1: Rewrite the handler to use `materialize_to_pgstac()`**

The handler still needs to:
1. Look up `stac_item_json` from `cog_metadata` or `zarr_metadata` (existing logic, keep it)
2. Call `materialize_to_pgstac()` instead of doing sanitization/injection/upsert inline

Replace the inline steps 2-6 (lines 102-155) with:

```python
        # Materialize to pgSTAC via single write path
        materializer = STACMaterializer()
        result = materializer.materialize_to_pgstac(
            stac_item_json=stac_item_json,
            collection_id=collection_id,
            blob_path=effective_blob_path,
        )

        if not result.get("success"):
            return {
                "success": False,
                "error": result.get("error", "Materialization failed"),
                "error_type": "MaterializationError",
                "retryable": True,
            }

        return {
            "success": True,
            "result": {
                "item_id": cog_id,
                "collection_id": collection_id,
                "pgstac_id": result.get("pgstac_id"),
            },
        }
```

- [ ] **Step 2: Remove now-unused imports**

Remove direct imports of `PgStacRepository`, `build_raster_stac_collection` — those are now inside `materialize_to_pgstac()`.

- [ ] **Step 3: Run all tests**

Run: `conda run -n azgeo pytest tests/ -v --tb=short`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add services/stac/handler_materialize_item.py
git commit -m "refactor: handler_materialize_item uses materialize_to_pgstac"
```

---

### Task 9: Rewire `handler_register.py` (zarr)

**Files:**
- Modify: `services/zarr/handler_register.py`

**Context:** This file builds zarr STAC items inline. Replace with `build_stac_item()` call using zarr-specific params.

- [ ] **Step 1: Read the current zarr builder**

Read: `services/zarr/handler_register.py` — understand what params are extracted and how the item dict is built.

- [ ] **Step 2: Replace inline builder with `build_stac_item()` call**

```python
from services.stac.stac_item_builder import build_stac_item

stac_item_json = build_stac_item(
    item_id=stac_item_id,
    collection_id=collection_id,
    bbox=bbox,
    asset_href=zarr_href,            # e.g. "abfs://container/store.zarr"
    asset_type="application/vnd+zarr",
    asset_key="zarr-store",
    datetime=datetime_val,           # from xarray time coord or None
    start_datetime=start_dt,
    end_datetime=end_dt,
    zarr_variables=variables,
    zarr_dimensions=dimensions,
    job_id=run_id,
    epoch=5,
)
```

- [ ] **Step 3: Delete the old inline builder code**

- [ ] **Step 4: Run tests**

Run: `conda run -n azgeo pytest tests/ -v --tb=short`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add services/zarr/handler_register.py
git commit -m "refactor: zarr handler_register uses build_stac_item"
```

---

### Task 9b: Add pgSTAC search registration to `handler_materialize_collection.py`

**Files:**
- Modify: `services/stac/handler_materialize_collection.py`

**Context:** The spec requires that pgSTAC search registration for tiled collections is owned by `handler_materialize_collection`, not by the item materialization path. After computing the collection extent, if the collection has multiple items, register a pgSTAC search for TiTiler mosaic rendering.

- [ ] **Step 1: Read the current handler**

Read: `services/stac/handler_materialize_collection.py` — understand the current extent recalculation logic.

- [ ] **Step 2: Add search registration after collection upsert**

After the collection is upserted with computed extent, add:

```python
# Register pgSTAC search for tiled collections (mosaic TiTiler preview)
from infrastructure.pgstac_repository import PgStacRepository
pgstac = PgStacRepository()
item_count = pgstac.count_items_in_collection(collection_id)

if item_count and item_count > 1:
    from services.pgstac_search_registration import PgSTACSearchRegistration
    registrar = PgSTACSearchRegistration()
    search_id = registrar.register_collection_search(
        collection_id=collection_id,
        bbox=bbox,
    )
    logger.info("Registered pgSTAC search for tiled collection %s: %s", collection_id, search_id)
```

Note: Check if `PgStacRepository` has a `count_items_in_collection()` method. If not, use `get_collection_items()` and check length, or add a simple count query.

- [ ] **Step 3: Run tests**

Run: `conda run -n azgeo pytest tests/ -v --tb=short`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add services/stac/handler_materialize_collection.py
git commit -m "feat: handler_materialize_collection registers pgSTAC search for tiled collections"
```

---

## Phase 3: Wire Up Epoch 4 + Admin Paths

### Task 10: Replace `build_raster_stac_collection()` callers

**Files:**
- Modify: `services/stac_collection.py` — replace `build_raster_stac_collection()` with import of `build_stac_collection()`
- Modify: `triggers/stac/service.py` — replace `build_raster_stac_collection()` import and call
- Modify: any other callers found via grep

- [ ] **Step 1: Find all callers**

Run: `grep -rn "build_raster_stac_collection" services/ triggers/ --include="*.py"`

- [ ] **Step 2: Replace each call with `build_stac_collection()` from the new location**

```python
from services.stac.stac_collection_builder import build_stac_collection
```

Map the old params: `license_val` -> `license`, `temporal_start` stays, add `temporal_end` where available.

- [ ] **Step 3: Delete `build_raster_stac_collection()` from `services/stac_collection.py`**

- [ ] **Step 4: Run tests**

Run: `conda run -n azgeo pytest tests/ -v --tb=short`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add services/stac_collection.py services/stac/stac_collection_builder.py
git commit -m "refactor: replace build_raster_stac_collection with build_stac_collection"
```

---

### Task 10b: Rewire `handler_process_raster_complete.py` (Epoch 4)

**Files:**
- Modify: `services/handler_process_raster_complete.py`
- Modify: `services/service_stac_metadata.py` (if it calls `RasterMetadata.to_stac_item()`)

**Context:** The Epoch 4 raster completion handler currently uses `StacMetadataService.extract_item_from_blob()` which calls `RasterMetadata.to_stac_item()` — the richest but Epoch-4-only builder. Replace with extracting fields from `RasterMetadata` and calling `build_stac_item()`.

- [ ] **Step 1: Read the current handler to understand the call chain**

Read: `services/handler_process_raster_complete.py` — find where `stac_item_json` is built/cached. Also read `services/service_stac_metadata.py` to find `RasterMetadata.to_stac_item()` callers.

- [ ] **Step 2: Replace `to_stac_item()` call with `build_stac_item()`**

Where the handler gets a `RasterMetadata` object, extract its fields and call:

```python
from services.stac.stac_item_builder import build_stac_item

stac_item_json = build_stac_item(
    item_id=metadata.stac_item_id,
    collection_id=metadata.stac_collection_id,
    bbox=[metadata.bbox_west, metadata.bbox_south, metadata.bbox_east, metadata.bbox_north],
    asset_href=metadata.cog_url,
    asset_type="image/tiff; application=geotiff; profile=cloud-optimized",
    crs=metadata.crs,
    transform=metadata.transform,
    raster_bands=metadata.raster_bands,
    detected_type=metadata.raster_type,
    band_count=metadata.band_count,
    data_type=metadata.data_type,
    dataset_id=getattr(metadata, 'dataset_id', None),
    resource_id=getattr(metadata, 'resource_id', None),
    version_id=getattr(metadata, 'version_id', None),
    iso3_codes=getattr(metadata, 'iso3_codes', None),
    primary_iso3=getattr(metadata, 'primary_iso3', None),
    country_names=getattr(metadata, 'country_names', None),
    job_id=job_id,
    epoch=4,
)
```

Note: The exact field names on `RasterMetadata` need to be checked by reading the file. The above is a template — adapt to actual attribute names.

- [ ] **Step 3: Run tests**

Run: `conda run -n azgeo pytest tests/ -v --tb=short`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add services/handler_process_raster_complete.py services/service_stac_metadata.py
git commit -m "refactor: Epoch 4 handler_process_raster_complete uses build_stac_item"
```

---

### Task 11: Fix admin paths to use `upsert_item()`

**Files:**
- Modify: `triggers/stac_extract.py` — change `create_item()` to `upsert_item()`
- Modify: `services/stac_catalog.py` — change `create_item()` to `upsert_item()`

- [ ] **Step 1: Find all `create_item` calls**

Run: `grep -rn "PgStacBootstrap.*insert_item\|\.create_item" services/ triggers/ --include="*.py"`

- [ ] **Step 2: Replace with `upsert_item()` via `PgStacRepository`**

Each `PgStacBootstrap.insert_item()` call should become `PgStacRepository().insert_item()` (which uses `pgstac.upsert_item()`).

- [ ] **Step 3: Run tests**

Run: `conda run -n azgeo pytest tests/ -v --tb=short`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add triggers/stac_extract.py services/stac_catalog.py
git commit -m "fix: admin STAC paths use upsert_item instead of create_item"
```

---

## Phase 4: Cleanup

### Task 12: Delete dead code

**Files:**
- Modify: `core/models/unified_metadata.py` — delete `RasterMetadata.to_stac_item()` method
- Modify: `services/stac_materialization.py` — delete `_materialize_zarr_item()` method
- Modify: `services/stac_collection.py` — delete pystac import and `_create_stac_collection_impl()` pystac usage

- [ ] **Step 1: Find and verify each deletion target is no longer called**

Run grep for each:
```bash
grep -rn "to_stac_item\|_materialize_zarr_item\|pystac.Collection" services/ triggers/ core/ --include="*.py"
```

Only proceed with deletion if grep shows zero callers (or only the definition itself).

- [ ] **Step 2: Delete dead code**

- [ ] **Step 3: Run full test suite**

Run: `conda run -n azgeo pytest tests/ -v --tb=short`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add core/models/unified_metadata.py services/stac_materialization.py services/stac_collection.py
git commit -m "chore: delete old STAC builders replaced by consolidation"
```

---

### Task 13: Final verification

- [ ] **Step 1: Run full test suite**

Run: `conda run -n azgeo pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 2: Verify no references to deleted code remain**

```bash
grep -rn "_build_stac_item_json\|_build_tile_stac_item\|build_raster_stac_collection\|_build_renders_for_stac\|_TEMPORAL_UNKNOWN\|to_stac_item\|PgStacBootstrap\|_materialize_zarr_item" services/ triggers/ core/ tests/ --include="*.py"
```

Expected: Zero matches (or only doc strings / comments).

- [ ] **Step 3: Commit with version bump**

Update `config/__init__.py` version to `0.10.6.0` (Composable STAC consolidation).

```bash
git add config/__init__.py
git commit -m "feat: STAC consolidation complete — one builder, one write path (v0.10.6.0)"
```
