"""Tests for Zarr format encoding compatibility (SG13-1, SG13-6)."""
import pytest
from core.models.processing_options import ZarrProcessingOptions


class TestZarrProcessingOptionsFormat:
    """ZarrProcessingOptions.zarr_format field."""

    def test_default_zarr_format_is_3(self):
        opts = ZarrProcessingOptions()
        assert opts.zarr_format == 3

    def test_zarr_format_2_accepted(self):
        opts = ZarrProcessingOptions(zarr_format=2)
        assert opts.zarr_format == 2

    def test_zarr_format_3_accepted(self):
        opts = ZarrProcessingOptions(zarr_format=3)
        assert opts.zarr_format == 3

    def test_zarr_format_invalid_rejected(self):
        with pytest.raises(Exception):  # ValidationError
            ZarrProcessingOptions(zarr_format=1)

    def test_zarr_format_invalid_4_rejected(self):
        with pytest.raises(Exception):
            ZarrProcessingOptions(zarr_format=4)


import numpy as np
import xarray as xr


def _make_test_dataset():
    """Create a minimal xarray Dataset for encoding tests."""
    return xr.Dataset({
        "temperature": xr.DataArray(
            np.zeros((3, 10, 20)),
            dims=["time", "lat", "lon"],
        )
    })


class TestBuildZarrEncodingV3:
    """_build_zarr_encoding with zarr_format=3 (default)."""

    def test_v3_returns_blosccodec(self):
        from services.handler_netcdf_to_zarr import _build_zarr_encoding
        ds = _make_test_dataset()
        _, encoding = _build_zarr_encoding(ds, zarr_format=3)
        compressors = encoding["temperature"]["compressors"]
        from zarr.codecs import BloscCodec
        assert isinstance(compressors[0], BloscCodec)

    def test_v3_uses_compressors_key(self):
        from services.handler_netcdf_to_zarr import _build_zarr_encoding
        ds = _make_test_dataset()
        _, encoding = _build_zarr_encoding(ds, zarr_format=3)
        assert "compressors" in encoding["temperature"]
        assert "compressor" not in encoding["temperature"]

    def test_v3_chunks_correct(self):
        from services.handler_netcdf_to_zarr import _build_zarr_encoding
        ds = _make_test_dataset()
        target_chunks, encoding = _build_zarr_encoding(
            ds, spatial_chunk_size=256, time_chunk_size=1, zarr_format=3
        )
        assert target_chunks["time"] == 1
        assert target_chunks["lat"] == 10  # clamped to dim size
        assert target_chunks["lon"] == 20  # clamped to dim size


class TestBuildZarrEncodingV2:
    """_build_zarr_encoding with zarr_format=2."""

    def test_v2_returns_numcodecs_blosc(self):
        from services.handler_netcdf_to_zarr import _build_zarr_encoding
        ds = _make_test_dataset()
        _, encoding = _build_zarr_encoding(ds, zarr_format=2)
        compressor = encoding["temperature"]["compressor"]
        import numcodecs
        assert isinstance(compressor, numcodecs.Blosc)

    def test_v2_uses_compressor_key(self):
        from services.handler_netcdf_to_zarr import _build_zarr_encoding
        ds = _make_test_dataset()
        _, encoding = _build_zarr_encoding(ds, zarr_format=2)
        assert "compressor" in encoding["temperature"]
        assert "compressors" not in encoding["temperature"]

    def test_v2_compressor_params(self):
        from services.handler_netcdf_to_zarr import _build_zarr_encoding
        ds = _make_test_dataset()
        _, encoding = _build_zarr_encoding(
            ds, compressor_name="zstd", compression_level=3, zarr_format=2
        )
        compressor = encoding["temperature"]["compressor"]
        assert compressor.cname == "zstd"
        assert compressor.clevel == 3


class TestBuildZarrEncodingNone:
    """_build_zarr_encoding with compressor='none'."""

    def test_v3_no_compressor(self):
        from services.handler_netcdf_to_zarr import _build_zarr_encoding
        ds = _make_test_dataset()
        _, encoding = _build_zarr_encoding(ds, compressor_name="none", zarr_format=3)
        assert "compressors" not in encoding["temperature"]
        assert "compressor" not in encoding["temperature"]

    def test_v2_no_compressor(self):
        from services.handler_netcdf_to_zarr import _build_zarr_encoding
        ds = _make_test_dataset()
        _, encoding = _build_zarr_encoding(ds, compressor_name="none", zarr_format=2)
        assert "compressors" not in encoding["temperature"]
        assert "compressor" not in encoding["temperature"]
