# ============================================================================
# BLOB-MOUNT TRANSFER MODELS
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Model - Pydantic models for blob ↔ mounted filesystem transfers
# PURPOSE: Type-safe requests/responses for streaming data between Azure Blob
#          Storage and mounted filesystems (Azure Files, local disk)
# CREATED: 25 JAN 2026
# EXPORTS: BlobToMountRequest, MountToBlobRequest, BlobMountTransferResult
# ============================================================================
"""
Blob-Mount Transfer Models.

These models provide strict type safety for operations that transfer data
between Azure Blob Storage and a mounted filesystem (e.g., Azure Files mount
on Docker workers).

Why This Matters:
    - Processing large files (>1GB) requires disk-based I/O to avoid OOM
    - Docker workers have Azure Files mounted at /mounts/etl-temp
    - GDAL can process files larger than RAM if given disk paths
    - Streaming transfers avoid loading entire files into memory

Naming Convention:
    - "Blob" = Azure Blob Storage (bronze/silver containers)
    - "Mount" = Mounted filesystem path (e.g., /mounts/etl-temp/file.tif)
    - "stream_blob_to_mount" = Download blob → write to mount (no RAM spike)
    - "stream_mount_to_blob" = Read from mount → upload blob (no RAM spike)

Usage:
    from core.models.blob_mount_transfer import (
        BlobToMountRequest,
        MountToBlobRequest,
        BlobMountTransferResult
    )

    # Download blob to mounted filesystem
    request = BlobToMountRequest(
        container="bronze-raster",
        blob_path="tiles/tile_001.tif",
        mount_path="/mounts/etl-temp/input_abc123.tif"
    )
    result = blob_repo.stream_blob_to_mount(request)

    # Upload from mounted filesystem to blob
    request = MountToBlobRequest(
        mount_path="/mounts/etl-temp/output_abc123.cog.tif",
        container="silver-cogs",
        blob_path="processed/tile_001.tif"
    )
    result = blob_repo.stream_mount_to_blob(request)
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# =============================================================================
# CONFIGURATION
# =============================================================================

# Default chunk size for streaming transfers (32 MB)
# Balances memory usage vs. network efficiency
DEFAULT_CHUNK_SIZE_MB = 32

# Maximum chunk size (256 MB) - larger chunks may cause memory pressure
MAX_CHUNK_SIZE_MB = 256

# Minimum chunk size (1 MB) - smaller chunks have too much overhead
MIN_CHUNK_SIZE_MB = 1


# =============================================================================
# REQUEST MODELS
# =============================================================================

class BlobToMountRequest(BaseModel):
    """
    Request to stream data from Azure Blob Storage to mounted filesystem.

    This operation downloads a blob in chunks, writing directly to disk
    without loading the entire file into memory. Essential for processing
    files larger than available RAM.

    Attributes:
        container: Source blob container name (e.g., "bronze-raster")
        blob_path: Source blob path within container
        mount_path: Destination path on mounted filesystem (must be absolute)
        chunk_size_mb: Size of each streaming chunk (default: 32MB)
        overwrite_existing: Whether to overwrite if file exists (default: True)

    Example:
        request = BlobToMountRequest(
            container="bronze-raster",
            blob_path="fathom/flood_depth_100yr.tif",
            mount_path="/mounts/etl-temp/input_f15d0d54.tif"
        )
    """

    container: str = Field(
        ...,
        min_length=1,
        max_length=63,
        description="Source blob container name"
    )
    blob_path: str = Field(
        ...,
        min_length=1,
        description="Source blob path within container"
    )
    mount_path: str = Field(
        ...,
        min_length=1,
        description="Destination path on mounted filesystem (absolute path)"
    )
    chunk_size_mb: int = Field(
        default=DEFAULT_CHUNK_SIZE_MB,
        ge=MIN_CHUNK_SIZE_MB,
        le=MAX_CHUNK_SIZE_MB,
        description="Streaming chunk size in MB"
    )
    overwrite_existing: bool = Field(
        default=True,
        description="Overwrite destination file if it exists"
    )

    @field_validator('mount_path')
    @classmethod
    def validate_mount_path_is_absolute(cls, v: str) -> str:
        """Ensure mount_path is an absolute path."""
        path = Path(v)
        if not path.is_absolute():
            raise ValueError(
                f"mount_path must be absolute, got relative path: {v}"
            )
        return v

    @field_validator('mount_path')
    @classmethod
    def validate_mount_path_parent_exists(cls, v: str) -> str:
        """Ensure parent directory exists (mount must be accessible)."""
        parent = Path(v).parent
        if not parent.exists():
            raise ValueError(
                f"Mount path parent directory does not exist: {parent}. "
                f"Is the filesystem mounted?"
            )
        return v

    @field_validator('blob_path')
    @classmethod
    def validate_blob_path_not_absolute(cls, v: str) -> str:
        """Blob paths should not start with /."""
        if v.startswith('/'):
            raise ValueError(
                f"blob_path should not start with /, got: {v}"
            )
        return v

    @property
    def chunk_size_bytes(self) -> int:
        """Get chunk size in bytes."""
        return self.chunk_size_mb * 1024 * 1024

    def get_source_uri(self) -> str:
        """Get human-readable source URI for logging."""
        return f"blob://{self.container}/{self.blob_path}"

    def get_destination_uri(self) -> str:
        """Get human-readable destination URI for logging."""
        return f"file://{self.mount_path}"


class MountToBlobRequest(BaseModel):
    """
    Request to stream data from mounted filesystem to Azure Blob Storage.

    This operation reads a file in chunks, uploading directly to blob storage
    without loading the entire file into memory. Essential for uploading
    large processed files (COGs, GeoParquet, etc.).

    Attributes:
        mount_path: Source path on mounted filesystem (must exist)
        container: Destination blob container name
        blob_path: Destination blob path within container
        content_type: MIME type for the blob (default: auto-detect)
        chunk_size_mb: Size of each streaming chunk (default: 32MB)
        overwrite_existing: Whether to overwrite if blob exists (default: True)

    Example:
        request = MountToBlobRequest(
            mount_path="/mounts/etl-temp/output_f15d0d54.cog.tif",
            container="silver-cogs",
            blob_path="processed/flood_depth_100yr.tif",
            content_type="image/tiff"
        )
    """

    mount_path: str = Field(
        ...,
        min_length=1,
        description="Source path on mounted filesystem (must exist)"
    )
    container: str = Field(
        ...,
        min_length=1,
        max_length=63,
        description="Destination blob container name"
    )
    blob_path: str = Field(
        ...,
        min_length=1,
        description="Destination blob path within container"
    )
    content_type: Optional[str] = Field(
        default=None,
        description="MIME type for the blob (auto-detected if not specified)"
    )
    chunk_size_mb: int = Field(
        default=DEFAULT_CHUNK_SIZE_MB,
        ge=MIN_CHUNK_SIZE_MB,
        le=MAX_CHUNK_SIZE_MB,
        description="Streaming chunk size in MB"
    )
    overwrite_existing: bool = Field(
        default=True,
        description="Overwrite destination blob if it exists"
    )

    @field_validator('mount_path')
    @classmethod
    def validate_mount_path_exists(cls, v: str) -> str:
        """Ensure source file exists."""
        if not Path(v).exists():
            raise ValueError(
                f"Source file does not exist: {v}"
            )
        return v

    @field_validator('mount_path')
    @classmethod
    def validate_mount_path_is_file(cls, v: str) -> str:
        """Ensure source is a file, not a directory."""
        path = Path(v)
        if path.exists() and path.is_dir():
            raise ValueError(
                f"mount_path must be a file, not a directory: {v}"
            )
        return v

    @field_validator('blob_path')
    @classmethod
    def validate_blob_path_not_absolute(cls, v: str) -> str:
        """Blob paths should not start with /."""
        if v.startswith('/'):
            raise ValueError(
                f"blob_path should not start with /, got: {v}"
            )
        return v

    @property
    def chunk_size_bytes(self) -> int:
        """Get chunk size in bytes."""
        return self.chunk_size_mb * 1024 * 1024

    @property
    def file_size_bytes(self) -> int:
        """Get source file size in bytes."""
        return os.path.getsize(self.mount_path)

    def get_content_type(self) -> str:
        """Get content type, auto-detecting if not specified."""
        if self.content_type:
            return self.content_type

        # Auto-detect based on extension
        ext = Path(self.mount_path).suffix.lower()
        content_types = {
            '.tif': 'image/tiff',
            '.tiff': 'image/tiff',
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.json': 'application/json',
            '.geojson': 'application/geo+json',
            '.parquet': 'application/vnd.apache.parquet',
            '.geoparquet': 'application/vnd.apache.parquet',
            '.gpkg': 'application/geopackage+sqlite3',
        }
        return content_types.get(ext, 'application/octet-stream')

    def get_source_uri(self) -> str:
        """Get human-readable source URI for logging."""
        return f"file://{self.mount_path}"

    def get_destination_uri(self) -> str:
        """Get human-readable destination URI for logging."""
        return f"blob://{self.container}/{self.blob_path}"


# =============================================================================
# RESULT MODEL
# =============================================================================

class BlobMountTransferResult(BaseModel):
    """
    Result of a blob ↔ mount transfer operation.

    Contains metrics and status for both download (blob→mount) and
    upload (mount→blob) operations.

    Attributes:
        success: Whether the transfer completed successfully
        operation: "blob_to_mount" or "mount_to_blob"
        bytes_transferred: Total bytes transferred
        duration_seconds: Total transfer duration
        throughput_mbps: Transfer speed in MB/s
        source_uri: Human-readable source location
        destination_uri: Human-readable destination location
        chunks_transferred: Number of chunks processed
        error_message: Error details if success=False

    Example:
        result = BlobMountTransferResult(
            success=True,
            operation="blob_to_mount",
            bytes_transferred=1_867_432_960,
            duration_seconds=45.2,
            throughput_mbps=39.4,
            source_uri="blob://bronze-raster/tile.tif",
            destination_uri="file:///mounts/etl-temp/input.tif",
            chunks_transferred=57
        )
    """

    success: bool = Field(..., description="Whether transfer succeeded")
    operation: str = Field(
        ...,
        pattern=r"^(blob_to_mount|mount_to_blob)$",
        description="Transfer direction"
    )
    bytes_transferred: int = Field(
        ...,
        ge=0,
        description="Total bytes transferred"
    )
    duration_seconds: float = Field(
        ...,
        ge=0,
        description="Total transfer duration in seconds"
    )
    throughput_mbps: float = Field(
        ...,
        ge=0,
        description="Transfer speed in MB/s"
    )
    source_uri: str = Field(..., description="Source location")
    destination_uri: str = Field(..., description="Destination location")
    chunks_transferred: int = Field(
        default=1,
        ge=0,
        description="Number of chunks processed"
    )
    chunk_size_mb: int = Field(
        default=DEFAULT_CHUNK_SIZE_MB,
        description="Chunk size used"
    )
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Transfer start time"
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        description="Transfer completion time"
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Error details if success=False"
    )

    @property
    def size_mb(self) -> float:
        """Get transfer size in MB."""
        return self.bytes_transferred / (1024 * 1024)

    @property
    def size_gb(self) -> float:
        """Get transfer size in GB."""
        return self.bytes_transferred / (1024 * 1024 * 1024)

    def to_log_dict(self) -> dict:
        """Get dictionary suitable for structured logging."""
        return {
            'success': self.success,
            'operation': self.operation,
            'bytes': self.bytes_transferred,
            'size_mb': round(self.size_mb, 2),
            'duration_s': round(self.duration_seconds, 2),
            'throughput_mbps': round(self.throughput_mbps, 2),
            'chunks': self.chunks_transferred,
            'source': self.source_uri,
            'destination': self.destination_uri,
        }

    @classmethod
    def from_transfer(
        cls,
        operation: str,
        source_uri: str,
        destination_uri: str,
        bytes_transferred: int,
        duration_seconds: float,
        chunks_transferred: int,
        chunk_size_mb: int = DEFAULT_CHUNK_SIZE_MB,
        error_message: Optional[str] = None
    ) -> 'BlobMountTransferResult':
        """
        Factory method to create result from transfer metrics.

        Args:
            operation: "blob_to_mount" or "mount_to_blob"
            source_uri: Source location
            destination_uri: Destination location
            bytes_transferred: Total bytes
            duration_seconds: Total duration
            chunks_transferred: Number of chunks
            chunk_size_mb: Chunk size used
            error_message: Error if failed

        Returns:
            BlobMountTransferResult instance
        """
        throughput = (bytes_transferred / (1024 * 1024)) / duration_seconds if duration_seconds > 0 else 0

        return cls(
            success=error_message is None,
            operation=operation,
            bytes_transferred=bytes_transferred,
            duration_seconds=duration_seconds,
            throughput_mbps=throughput,
            source_uri=source_uri,
            destination_uri=destination_uri,
            chunks_transferred=chunks_transferred,
            chunk_size_mb=chunk_size_mb,
            completed_at=datetime.now(timezone.utc),
            error_message=error_message
        )


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = [
    'BlobToMountRequest',
    'MountToBlobRequest',
    'BlobMountTransferResult',
    'DEFAULT_CHUNK_SIZE_MB',
    'MAX_CHUNK_SIZE_MB',
    'MIN_CHUNK_SIZE_MB',
]
