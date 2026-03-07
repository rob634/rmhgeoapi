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
