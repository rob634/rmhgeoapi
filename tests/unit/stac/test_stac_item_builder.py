"""Unit tests for the canonical STAC item builder."""
import pytest


class TestBuildStacItemRequired:
    """Tests for required fields and minimal items."""

    def test_minimal_raster_item_has_required_fields(self):
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
        assert any("projection" in e for e in item["stac_extensions"])

    def test_wkt_crs_sets_proj_wkt2(self):
        from services.stac.stac_item_builder import build_stac_item
        item = build_stac_item(
            item_id="t1", collection_id="c1",
            bbox=[0, 0, 1, 1],
            asset_href="/vsiaz/silver/t.tif",
            asset_type="image/tiff; application=geotiff; profile=cloud-optimized",
            crs='PROJCS["WGS 84"]',
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

    def test_extensions_minimal_when_nothing_optional(self):
        from services.stac.stac_item_builder import build_stac_item
        item = build_stac_item(
            item_id="t1", collection_id="c1",
            bbox=[0, 0, 1, 1],
            asset_href="/vsiaz/silver/t.tif",
            asset_type="image/tiff; application=geotiff; profile=cloud-optimized",
        )
        ext = item["stac_extensions"]
        assert len(ext) == 1
        assert "processing" in ext[0]


class TestBuildStacItemZarr:

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
