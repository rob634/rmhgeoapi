"""Tests for BlobRepository.delete_blobs_by_prefix safety guards and batching."""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock


class FakeBlob:
    """Minimal blob object with a .name attribute."""
    def __init__(self, name: str):
        self.name = name


@pytest.fixture
def blob_repo():
    """Create a BlobRepository with mocked Azure clients."""
    with patch("infrastructure.blob.BlobRepository.__init__", return_value=None):
        from infrastructure.blob import BlobRepository
        repo = BlobRepository.__new__(BlobRepository)
        # Mock container_exists so the @dec_validate_container decorator passes
        repo.container_exists = MagicMock(return_value=True)
        repo._get_container_client = MagicMock()
        return repo


class TestDeleteBlobsByPrefixGuards:
    """Safety guards reject dangerous inputs."""

    def test_empty_prefix_raises(self, blob_repo):
        with pytest.raises(ValueError, match="non-empty prefix"):
            blob_repo.delete_blobs_by_prefix("container", "")

    def test_whitespace_prefix_raises(self, blob_repo):
        with pytest.raises(ValueError, match="non-empty prefix"):
            blob_repo.delete_blobs_by_prefix("container", "   ")

    def test_none_prefix_raises(self, blob_repo):
        with pytest.raises(ValueError, match="non-empty prefix"):
            blob_repo.delete_blobs_by_prefix("container", None)

    def test_single_segment_prefix_raises(self, blob_repo):
        with pytest.raises(ValueError, match="at least 2 path segments"):
            blob_repo.delete_blobs_by_prefix("container", "dataset_id")

    def test_two_segment_prefix_accepted(self, blob_repo):
        mock_client = blob_repo._get_container_client.return_value
        mock_client.list_blobs.return_value = []
        result = blob_repo.delete_blobs_by_prefix("container", "dataset_id/resource_id")
        assert result["deleted_count"] == 0


class TestDeleteBlobsByPrefixBehavior:
    """Functional behavior — listing, batching, counting."""

    def test_no_blobs_returns_zero(self, blob_repo):
        mock_client = blob_repo._get_container_client.return_value
        mock_client.list_blobs.return_value = []

        result = blob_repo.delete_blobs_by_prefix("container", "ds/res")
        assert result == {"deleted_count": 0, "prefix": "ds/res", "container": "container"}
        mock_client.delete_blobs.assert_not_called()

    def test_deletes_all_listed_blobs(self, blob_repo):
        mock_client = blob_repo._get_container_client.return_value
        mock_client.list_blobs.return_value = [
            FakeBlob("ds/res/.zmetadata"),
            FakeBlob("ds/res/.zgroup"),
            FakeBlob("ds/res/var/0.0"),
        ]

        result = blob_repo.delete_blobs_by_prefix("container", "ds/res")
        assert result["deleted_count"] == 3
        mock_client.delete_blobs.assert_called_once()

    def test_batches_at_256(self, blob_repo):
        mock_client = blob_repo._get_container_client.return_value
        mock_client.list_blobs.return_value = [
            FakeBlob(f"ds/res/chunk/{i}") for i in range(300)
        ]

        result = blob_repo.delete_blobs_by_prefix("container", "ds/res")
        assert result["deleted_count"] == 300
        # 300 blobs → 2 batch calls (256 + 44)
        assert mock_client.delete_blobs.call_count == 2

        first_call_args = mock_client.delete_blobs.call_args_list[0][0]
        second_call_args = mock_client.delete_blobs.call_args_list[1][0]
        assert len(first_call_args) == 256
        assert len(second_call_args) == 44

    def test_passes_prefix_to_list_blobs(self, blob_repo):
        mock_client = blob_repo._get_container_client.return_value
        mock_client.list_blobs.return_value = []

        blob_repo.delete_blobs_by_prefix("container", "ds/res/sub")
        mock_client.list_blobs.assert_called_once_with(name_starts_with="ds/res/sub")
