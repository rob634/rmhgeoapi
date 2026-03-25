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
        assert item["properties"]["datetime"] == "0001-01-01T00:00:00Z"
        assert len(item["properties"]) == 1
        assert "data" in item["assets"]
        assert item["assets"]["data"]["href"] == "/vsiaz/silver/tile_R0C0.tif"
        assert item["assets"]["data"]["roles"] == ["data"]
