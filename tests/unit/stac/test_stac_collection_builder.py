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
