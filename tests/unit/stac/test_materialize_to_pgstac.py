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
        call_args = m._pgstac.insert_item.call_args
        inserted_item = call_args[0][0]
        props = inserted_item["properties"]
        assert not any(k.startswith("geoetl:") for k in props)
        assert not any(k.startswith("processing:") for k in props)
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
        m.materialize_to_pgstac(stac_item_json=original, collection_id="test-coll")
        assert set(original["properties"].keys()) == original_props_keys

    @patch("services.stac_materialization.STACMaterializer._inject_titiler_urls")
    def test_auto_creates_collection_if_missing(self, mock_inject):
        from services.stac_materialization import STACMaterializer
        m = STACMaterializer()
        m._pgstac = MagicMock()
        m._pgstac.get_collection.return_value = None
        m._pgstac.insert_item.return_value = "pgstac-id-1"
        m._pgstac.insert_collection = MagicMock()
        m.materialize_to_pgstac(stac_item_json=_sample_cached_item(), collection_id="new-coll")
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
        result = m.materialize_to_pgstac(stac_item_json=_sample_cached_item(), collection_id="test-coll")
        assert m._pgstac.insert_item.called
        assert result["success"] is True
        assert result["pgstac_id"] == "pgstac-id-1"
