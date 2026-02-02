# ============================================================================
# BLOB STORAGE REPOSITORY
# ============================================================================
# STATUS: Infrastructure - Azure Blob Storage access
# PURPOSE: Centralized blob operations with DefaultAzureCredential
# LAST_REVIEWED: 21 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 ref: config/storage_config.py)
# ============================================================================
"""
Blob Storage Repository.

================================================================================
DEPLOYMENT NOTE
================================================================================

Azure Storage account configuration is in:
    config/storage_config.py (has full Check 8 deployment guide)

This module USES those settings - see storage_config.py for:
    - Storage account service request template
    - Container creation requirements
    - Managed identity role assignments (Storage Blob Data Contributor)
    - Trust zone architecture (Bronze/Silver/SilverExternal)
    - Verification commands

Key Role Assignments Required:
    - Storage Blob Data Contributor: Read/write blob data
    - Storage Blob Delegator: Generate user delegation SAS tokens

Authentication Flow:
    DefaultAzureCredential automatically tries (in order):
    1. Environment variables (AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_CLIENT_SECRET)
    2. Managed Identity (when running in Azure)
    3. Azure CLI (local development: az login)
    4. Visual Studio Code Azure extension
    5. Azure PowerShell

================================================================================

Centralized blob storage repository with managed authentication using
DefaultAzureCredential. Serves as the single point of authentication
for all blob operations across the entire ETL pipeline.

Key Features:
- DefaultAzureCredential for seamless authentication across environments
- Singleton pattern ensures connection reuse
- Connection pooling for container clients
- All ETL services use this for blob access
- No credential management needed in services

Authentication Hierarchy:
1. Environment variables (AZURE_CLIENT_ID, etc.)
2. Managed Identity (in Azure)
3. Azure CLI (local development)
4. Visual Studio Code
5. Azure PowerShell

Exports:
    IBlobRepository: Abstract interface for blob operations
    BlobRepository: Singleton blob storage implementation

Dependencies:
    azure.storage.blob: Blob Storage SDK
    azure.identity: DefaultAzureCredential for authentication
    util_logger: Structured logging
    infrastructure.decorators_blob: Validation decorators

Usage:
    from .factory import RepositoryFactory

    # Get authenticated repository
    blob_repo = RepositoryFactory.create_blob_repository()

    # Use without worrying about credentials
    data = blob_repo.read_blob('bronze', 'path/to/file.tif')
"""

# ============================================================================
# IMPORTS - Top of file for fail-fast behavior
# ============================================================================

# Standard library imports
import os
import logging
import threading
import concurrent.futures
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from io import BytesIO
from typing import List, Dict, Any, Optional, Iterator, BinaryIO, Union

# Azure SDK imports - These will fail fast if not installed
from azure.storage.blob import BlobServiceClient, ContainerClient, BlobClient, generate_blob_sas, BlobSasPermissions, ContentSettings
from azure.identity import DefaultAzureCredential
from azure.core.exceptions import ResourceNotFoundError

# Application imports
from util_logger import LoggerFactory, ComponentType
from infrastructure.decorators_blob import (
    validate_container as dec_validate_container,
    validate_blob as dec_validate_blob,
    validate_container_and_blob as dec_validate_container_and_blob
)

logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, __name__)


# ============================================================================
# BLOB REPOSITORY INTERFACE
# ============================================================================

class IBlobRepository(ABC):
    """
    Interface for blob storage operations.

    Enables dependency injection and testing/mocking of blob operations.
    All blob repositories must implement this interface.
    """

    @abstractmethod
    def container_exists(self, container: str) -> bool:
        """Check if container exists"""
        pass

    @abstractmethod
    def validate_container_and_blob(self, container: str, blob_path: str) -> Dict[str, Any]:
        """
        Validate both container and blob existence.

        Returns dict with container_exists, blob_exists, valid, and message fields.
        """
        pass

    @abstractmethod
    def read_blob(self, container: str, blob_path: str) -> bytes:
        """Read entire blob to memory"""
        pass

    @abstractmethod
    def write_blob(self, container: str, blob_path: str, data: Union[bytes, BinaryIO],
                   overwrite: bool = True, content_type: str = "application/octet-stream",
                   metadata: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Write blob from bytes or stream"""
        pass

    @abstractmethod
    def list_blobs(self, container: str, prefix: str = "", limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """List blobs with metadata"""
        pass

    @abstractmethod
    def blob_exists(self, container: str, blob_path: str) -> bool:
        """Check if blob exists"""
        pass

    @abstractmethod
    def delete_blob(self, container: str, blob_path: str) -> bool:
        """Delete a blob"""
        pass

    @abstractmethod
    def stream_blob_to_mount(
        self,
        container: str,
        blob_path: str,
        mount_path: str,
        chunk_size_mb: int = 32
    ) -> Dict[str, Any]:
        """
        Stream blob directly to mounted filesystem without loading into memory.

        Args:
            container: Source blob container name
            blob_path: Source blob path within container
            mount_path: Destination path on mounted filesystem (absolute path)
            chunk_size_mb: Streaming chunk size in MB (default: 32)

        Returns:
            Dict with transfer result including bytes_transferred, duration, throughput
        """
        pass

    @abstractmethod
    def stream_mount_to_blob(
        self,
        container: str,
        blob_path: str,
        mount_path: str,
        content_type: Optional[str] = None,
        chunk_size_mb: int = 32
    ) -> Dict[str, Any]:
        """
        Stream file from mounted filesystem to blob without loading into memory.

        Args:
            container: Destination blob container name
            blob_path: Destination blob path within container
            mount_path: Source path on mounted filesystem (must exist)
            content_type: MIME type for blob (auto-detected if not specified)
            chunk_size_mb: Streaming chunk size in MB (default: 32)

        Returns:
            Dict with transfer result including bytes_transferred, duration, throughput
        """
        pass


# ============================================================================
# BLOB REPOSITORY IMPLEMENTATION
# ============================================================================

class BlobRepository(IBlobRepository):
    """
    Multi-account blob storage repository with trust zone awareness.

    CRITICAL: This is THE authentication point for all blob operations.
    - Uses DefaultAzureCredential for seamless auth across environments
    - Multi-instance singleton pattern (one instance PER storage account)
    - All ETL services use this for blob access

    Design Principles:
    - Single source of authentication for all blob operations
    - Separate connection pools per storage account (Bronze/Silver/SilverExternal)
    - Thread-safe multi-instance singleton (05 JAN 2026: uses locks for 8+ instances)
    - Double-checked locking for container client caching
    - Consistent error handling and logging

    Usage:
        # Get repository for specific trust zone (RECOMMENDED)
        bronze_repo = BlobRepository.for_zone("bronze")
        silver_repo = BlobRepository.for_zone("silver")

        # Or through factory (also recommended)
        bronze_repo = RepositoryFactory.create_blob_repository("bronze")

        # Legacy usage still works (defaults to Silver)
        blob_repo = BlobRepository.instance()
    """

    # Multi-instance singleton: one instance per storage account
    _instances: Dict[str, 'BlobRepository'] = {}
    _instances_lock = threading.Lock()  # Thread-safe singleton creation (05 JAN 2026)

    def __new__(cls, account_name: str = None, connection_string: Optional[str] = None, *args, **kwargs):
        """
        Multi-instance singleton creation.

        Creates one singleton instance PER storage account.
        This allows separate connection pools for Bronze/Silver/SilverExternal.

        Args:
            account_name: Storage account name (defaults to Silver account from config)
            connection_string: Optional connection string for compatibility
        """
        # Determine account name
        if account_name is None:
            # Default to Silver account for backward compatibility
            from config import get_config
            account_name = get_config().storage.silver.account_name

        # Thread-safe singleton creation (05 JAN 2026)
        # Prevents race condition when multiple threads create instances simultaneously
        with cls._instances_lock:
            if account_name not in cls._instances:
                instance = super().__new__(cls)
                cls._instances[account_name] = instance
            return cls._instances[account_name]
    
    def __init__(self, account_name: str = None, connection_string: Optional[str] = None):
        """
        Initialize blob repository for specific storage account.

        Args:
            account_name: Storage account name (defaults to Silver)
            connection_string: Optional connection string for airgapped accounts
        """
        # Prevent re-initialization of existing instance
        if hasattr(self, '_initialized') and self._initialized:
            return

        from config import get_config
        config = get_config()

        # Determine account name
        self.account_name = account_name or config.storage.silver.account_name

        try:
            # Use connection string if provided (for airgapped SilverExternal)
            if connection_string:
                logger.info(f"Initializing BlobRepository with connection string for {self.account_name}")
                self.blob_service = BlobServiceClient.from_connection_string(connection_string)
            else:
                # Use DefaultAzureCredential (for Bronze/Silver)
                self.account_url = f"https://{self.account_name}.blob.core.windows.net"
                logger.info(f"Initializing BlobRepository with DefaultAzureCredential for {self.account_name}")

                # Create credential
                self.credential = DefaultAzureCredential()

                # Create blob service client
                self.blob_service = BlobServiceClient(
                    account_url=self.account_url,
                    credential=self.credential
                )

            # Cache container clients with thread-safe lock (05 JAN 2026)
            self._container_clients: Dict[str, ContainerClient] = {}
            self._container_clients_lock = threading.Lock()

            # Pre-cache containers for THIS account
            self._pre_cache_containers(config)

            self._initialized = True
            logger.info(f"✅ BlobRepository initialized for account: {self.account_name}")

        except Exception as e:
            logger.error(f"Failed to initialize BlobRepository for {self.account_name}: {e}")
            raise

    def _pre_cache_containers(self, config):
        """
        Pre-cache container clients based on account name.

        Determines which trust zone (bronze/silver/silverext) this instance
        represents and caches appropriate containers.
        """
        # Determine which account we are
        if self.account_name == config.storage.bronze.account_name:
            zone_config = config.storage.bronze
            logger.debug("Pre-caching BRONZE containers")
        elif self.account_name == config.storage.silver.account_name:
            zone_config = config.storage.silver
            logger.debug("Pre-caching SILVER containers")
        elif self.account_name == config.storage.silverext.account_name:
            zone_config = config.storage.silverext
            logger.debug("Pre-caching SILVER EXTERNAL containers")
        else:
            logger.warning(f"Unknown account {self.account_name}, skipping pre-cache")
            return

        # Cache all containers for this zone
        containers_to_cache = [
            zone_config.vectors,
            zone_config.rasters,
            zone_config.cogs,
            zone_config.tiles,
            zone_config.mosaicjson,
            zone_config.stac_assets,
            zone_config.misc,
            zone_config.temp
        ]

        for container in containers_to_cache:
            if "notused" in container:
                continue  # Skip unused containers (e.g., bronze-cogs)

            try:
                self._get_container_client(container)
                logger.debug(f"Pre-cached container: {container}")
            except Exception as e:
                logger.warning(f"Could not pre-cache container {container}: {e}")
    
    @classmethod
    def for_zone(cls, zone: str) -> 'BlobRepository':
        """
        Get BlobRepository instance for a trust zone.

        This is the RECOMMENDED factory method for multi-account access.

        Args:
            zone: Trust zone ("bronze", "silver", "silverext")

        Returns:
            BlobRepository connected to that zone's storage account

        Example:
            # ETL reads from Bronze (untrusted user uploads)
            bronze_repo = BlobRepository.for_zone("bronze")
            raw_data = bronze_repo.read_blob("bronze-rasters", "user_upload.tif")

            # ETL writes to Silver (trusted processed data)
            silver_repo = BlobRepository.for_zone("silver")
            silver_repo.write_blob("silver-cogs", "processed.tif", cog_data)

            # Future: Sync to SilverExternal (airgapped replica)
            ext_repo = BlobRepository.for_zone("silverext")
            ext_repo.write_blob("silverext-cogs", "processed.tif", cog_data)

        Raises:
            ValueError: If zone is unknown
        """
        from config import get_config
        config = get_config()

        zone_config = config.storage.get_account(zone)

        # StorageAccountConfig only has account_name, not connection_string
        # BlobRepository.__init__ will use DefaultAzureCredential for auth
        return cls(account_name=zone_config.account_name)

    @classmethod
    def instance(cls, account_name: Optional[str] = None, connection_string: Optional[str] = None) -> 'BlobRepository':
        """
        Get singleton instance (backward compatible).

        DEPRECATED: Use for_zone() instead for multi-account support.

        Args:
            account_name: Optional storage account name (defaults to Silver)
            connection_string: Optional connection string

        Returns:
            BlobRepository singleton instance (defaults to Silver zone)
        """
        return cls(account_name=account_name, connection_string=connection_string)
    
    def _get_container_client(self, container: str, validate: bool = False) -> ContainerClient:
        """
        Get or create cached container client with optional validation.

        Uses connection pooling by caching container clients.
        Optionally validates container existence for fail-fast error handling.

        Thread-safe implementation (05 JAN 2026):
        Uses double-checked locking pattern to minimize lock contention while
        preventing race conditions during container client creation.

        Args:
            container: Container name
            validate: If True, verify container exists before returning client (default: False)

        Returns:
            Cached or new ContainerClient

        Raises:
            ResourceNotFoundError: If validate=True and container doesn't exist
        """
        # Fast path: check without lock (common case - container already cached)
        if container in self._container_clients:
            return self._container_clients[container]

        # Slow path: acquire lock for thread-safe creation
        with self._container_clients_lock:
            # Double-check after acquiring lock (another thread may have created it)
            if container in self._container_clients:
                return self._container_clients[container]

            # Create new container client
            container_client = self.blob_service.get_container_client(container)

            # Validate container exists if requested
            if validate:
                try:
                    container_client.get_container_properties()
                except ResourceNotFoundError:
                    logger.error(f"Container does not exist: {container}")
                    raise ResourceNotFoundError(
                        f"Container '{container}' does not exist in storage account '{self.account_name}'"
                    )

            self._container_clients[container] = container_client
            logger.debug(f"Created new container client for: {container}")
            return container_client
    
    # ========================================================================
    # VALIDATION OPERATIONS
    # ========================================================================

    def container_exists(self, container: str) -> bool:
        """
        Check if container exists.

        Validates container existence before expensive operations.
        Use this for pre-flight checks to fail fast with clear errors.

        Args:
            container: Container name

        Returns:
            True if container exists, False otherwise

        Raises:
            Exception: For errors other than ResourceNotFoundError
        """
        try:
            container_client = self.blob_service.get_container_client(container)
            container_client.get_container_properties()
            logger.debug(f"Container exists: {container}")
            return True
        except ResourceNotFoundError:
            logger.debug(f"Container does not exist: {container}")
            return False
        except Exception as e:
            logger.error(f"Error checking container existence for '{container}': {e}")
            raise

    def ensure_container_exists(self, container: str) -> Dict[str, Any]:
        """
        Ensure container exists, creating it if necessary.

        Idempotent operation - safe to call multiple times.
        Used by full-rebuild to ensure critical containers exist.

        Args:
            container: Container name to ensure exists

        Returns:
            Dict with operation result:
            {
                "container": str,
                "existed": bool,  # True if already existed
                "created": bool,  # True if we created it
                "success": bool
            }

        Raises:
            Exception: For permission or other errors
        """
        result = {
            "container": container,
            "existed": False,
            "created": False,
            "success": False
        }

        try:
            # Check if already exists
            if self.container_exists(container):
                result["existed"] = True
                result["success"] = True
                logger.debug(f"Container already exists: {container}")
                return result

            # Create container
            container_client = self.blob_service.get_container_client(container)
            container_client.create_container()

            result["created"] = True
            result["success"] = True
            logger.info(f"✅ Created container: {container}")
            return result

        except Exception as e:
            logger.error(f"Failed to ensure container {container} exists: {e}")
            result["error"] = str(e)
            return result

    def validate_container_and_blob(self, container: str, blob_path: str) -> Dict[str, Any]:
        """
        Validate both container and blob existence.

        Useful for pre-flight checks before expensive operations.
        Provides clear diagnostic information about what exists and what doesn't.

        Args:
            container: Container name
            blob_path: Blob path

        Returns:
            Dict with validation results:
            {
                "container_exists": bool,
                "blob_exists": bool,
                "valid": bool,  # True if both exist
                "message": str  # Descriptive message
            }

        Example:
            result = blob_repo.validate_container_and_blob('bronze', 'data.tif')
            if not result['valid']:
                logger.error(result['message'])
                return {"success": False, "error": result['message']}
        """
        result = {
            "container_exists": False,
            "blob_exists": False,
            "valid": False,
            "message": ""
        }

        # Check container first
        if not self.container_exists(container):
            result["message"] = f"Container '{container}' does not exist in storage account '{self.account_name}'"
            return result

        result["container_exists"] = True

        # Check blob
        if not self.blob_exists(container, blob_path):
            result["message"] = f"Blob '{blob_path}' does not exist in container '{container}'"
            return result

        result["blob_exists"] = True
        result["valid"] = True
        result["message"] = f"Both container '{container}' and blob '{blob_path}' exist"

        return result

    # ========================================================================
    # CORE BLOB OPERATIONS
    # ========================================================================

    @dec_validate_container_and_blob
    def read_blob(self, container: str, blob_path: str) -> bytes:
        """
        Read entire blob to memory.

        Best for small files (<100MB). For larger files, use read_blob_chunked.
        Container and blob existence validated automatically by decorator.

        Args:
            container: Container name
            blob_path: Path to blob

        Returns:
            Blob content as bytes

        Raises:
            ResourceNotFoundError: If container or blob doesn't exist (validated pre-flight)
        """
        try:
            container_client = self._get_container_client(container)
            blob_client = container_client.get_blob_client(blob_path)
            
            logger.debug(f"Reading blob: {container}/{blob_path}")
            data = blob_client.download_blob().readall()
            
            logger.debug(f"Successfully read {len(data)} bytes from {container}/{blob_path}")
            return data
            
        except ResourceNotFoundError:
            logger.error(f"Blob not found: {container}/{blob_path}")
            raise
        except Exception as e:
            logger.error(f"Failed to read blob {container}/{blob_path}: {e}")
            raise
    
    def read_blob_to_stream(self, container: str, blob_path: str) -> BytesIO:
        """
        Read blob to BytesIO stream.
        
        Memory efficient way to read blobs for processing.
        
        Args:
            container: Container name
            blob_path: Path to blob
            
        Returns:
            BytesIO stream with blob content
        """
        data = self.read_blob(container, blob_path)
        return BytesIO(data)
    
    @dec_validate_container_and_blob
    def read_blob_chunked(self, container: str, blob_path: str, chunk_size: int = 4*1024*1024) -> Iterator[bytes]:
        """
        Stream blob in chunks for large files.

        Container and blob existence validated automatically by decorator.

        Args:
            container: Container name
            blob_path: Path to blob
            chunk_size: Size of each chunk (default 4MB)

        Yields:
            Chunks of blob data
        """
        try:
            container_client = self._get_container_client(container)
            blob_client = container_client.get_blob_client(blob_path)
            
            logger.debug(f"Streaming blob in chunks: {container}/{blob_path}")
            stream = blob_client.download_blob()
            
            for chunk in stream.chunks():
                yield chunk
                
        except Exception as e:
            logger.error(f"Failed to stream blob {container}/{blob_path}: {e}")
            raise
    
    @dec_validate_container
    def write_blob(self, container: str, blob_path: str, data: Union[bytes, BinaryIO],
                   overwrite: bool = True, content_type: str = "application/octet-stream",
                   metadata: Optional[Dict[str, str]] = None,
                   compute_checksum: bool = False) -> Dict[str, Any]:
        """
        Write blob from bytes or stream with optional STAC-compliant checksum.

        Container existence validated automatically by decorator.
        Blob doesn't need to exist (we're creating/overwriting it).

        Args:
            container: Container name
            blob_path: Path for blob
            data: Bytes or stream to write
            overwrite: Whether to overwrite existing blob
            content_type: MIME type for blob
            metadata: Optional metadata dictionary
            compute_checksum: If True, compute SHA-256 multihash (STAC file:checksum format)

        Returns:
            Dict with blob properties:
                - container, blob_path, size, etag, last_modified
                - blob_version_id: Azure version ID (only if versioning enabled on container)
                - file_checksum: SHA-256 multihash (only if compute_checksum=True)
                - file_size: Exact byte count (only if compute_checksum=True)
                - checksum_time_ms: Computation time in ms (only if compute_checksum=True)

        Note:
            Checksum computation adds ~5ms per MB of data (CPU only, no I/O).
            For a 500MB file, expect ~2.5 seconds overhead.
            blob_version_id is only populated if blob versioning is enabled on the
            storage account. See: az storage account blob-service-properties update
            --enable-versioning true
        """
        try:
            container_client = self._get_container_client(container)
            blob_client = container_client.get_blob_client(blob_path)

            # If computing checksum, ensure data is bytes (not stream)
            # and compute before upload (bytes already in memory)
            file_checksum = None
            file_size = None
            checksum_time_ms = None

            if compute_checksum:
                import time
                from utils.checksum import compute_multihash

                # Convert stream to bytes if needed
                if hasattr(data, 'read'):
                    data = data.read()

                file_size = len(data)
                checksum_start = time.time()
                file_checksum = compute_multihash(data, log_performance=False)
                checksum_time_ms = (time.time() - checksum_start) * 1000

                logger.debug(
                    f"Computed checksum for {container}/{blob_path}: "
                    f"{file_size} bytes in {checksum_time_ms:.0f}ms"
                )

            logger.debug(f"Writing blob: {container}/{blob_path} (overwrite={overwrite})")

            # Upload blob and capture response (includes version_id if versioning enabled)
            upload_response = blob_client.upload_blob(
                data,
                overwrite=overwrite,
                content_settings=ContentSettings(content_type=content_type),
                metadata=metadata or {}
            )

            # Get properties of written blob
            properties = blob_client.get_blob_properties()

            # Extract version_id from upload response (only present if versioning enabled)
            # Azure returns version_id as a string like "2024-01-21T12:34:56.1234567Z"
            blob_version_id = None
            if upload_response and hasattr(upload_response, 'get'):
                blob_version_id = upload_response.get('version_id')
            elif upload_response and hasattr(upload_response, 'version_id'):
                blob_version_id = upload_response.version_id

            result = {
                'container': container,
                'blob_path': blob_path,
                'size': properties.size,
                'etag': properties.etag,
                'last_modified': properties.last_modified.isoformat() if properties.last_modified else None,
                'blob_version_id': blob_version_id  # None if versioning not enabled
            }

            # Add checksum fields if computed
            if compute_checksum:
                result['file_checksum'] = file_checksum
                result['file_size'] = file_size
                result['checksum_time_ms'] = round(checksum_time_ms, 1)

            logger.info(f"✅ Wrote blob: {container}/{blob_path} ({properties.size} bytes)")
            return result

        except Exception as e:
            logger.error(f"Failed to write blob {container}/{blob_path}: {e}")
            raise
    
    def copy_blob(self, source_container: str, source_path: str,
                  dest_container: str, dest_path: str) -> Dict[str, Any]:
        """
        Server-side blob copy (no data transfer to client).
        
        Args:
            source_container: Source container name
            source_path: Source blob path
            dest_container: Destination container name
            dest_path: Destination blob path
            
        Returns:
            Dict with copy operation details
        """
        try:
            source_url = f"{self.account_url}/{source_container}/{source_path}"
            dest_client = self._get_container_client(dest_container).get_blob_client(dest_path)
            
            logger.debug(f"Copying blob: {source_container}/{source_path} → {dest_container}/{dest_path}")
            
            copy_operation = dest_client.start_copy_from_url(source_url)
            
            result = {
                'copy_id': copy_operation.get('copy_id'),
                'copy_status': copy_operation.get('copy_status')
            }
            
            logger.info(f"✅ Copy initiated: {source_container}/{source_path} → {dest_container}/{dest_path}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to copy blob: {e}")
            raise
    
    @dec_validate_container
    def list_blobs(self, container: str, prefix: str = "", limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        List blobs with metadata.

        Container existence validated automatically by decorator.

        Special handling for .gdb (Esri File Geodatabase) folders:
        - Treats entire .gdb as a single unit
        - Aggregates size of all files within .gdb
        - Returns .gdb as single entry instead of individual files

        Args:
            container: Container name
            prefix: Optional path prefix filter
            limit: Maximum number of blobs to return

        Returns:
            List of blob metadata dictionaries
        """
        try:
            container_client = self._get_container_client(container)
            blobs = []
            gdb_aggregates = {}  # Track .gdb folders and their aggregate data
            count = 0

            logger.debug(f"Listing blobs in {container} with prefix='{prefix}', limit={limit}")

            for blob in container_client.list_blobs(name_starts_with=prefix):
                blob_name = blob.name

                # Check if this blob is inside a .gdb folder
                gdb_match = None
                path_parts = blob_name.split('/')
                for i, part in enumerate(path_parts):
                    if part.endswith('.gdb'):
                        # Found a .gdb folder - construct its path
                        gdb_path = '/'.join(path_parts[:i+1])
                        gdb_match = gdb_path
                        break

                if gdb_match:
                    # This file is inside a .gdb - aggregate it
                    if gdb_match not in gdb_aggregates:
                        gdb_aggregates[gdb_match] = {
                            'name': gdb_match,
                            'size': 0,
                            'last_modified': blob.last_modified,
                            'content_type': 'application/x-esri-geodatabase',
                            'etag': None,  # No single etag for aggregate
                            'metadata': {'type': 'geodatabase', 'file_count': 0}
                        }

                    # Aggregate size and track latest modification
                    gdb_aggregates[gdb_match]['size'] += blob.size or 0
                    gdb_aggregates[gdb_match]['metadata']['file_count'] += 1

                    # Keep the most recent last_modified date
                    if blob.last_modified and gdb_aggregates[gdb_match]['last_modified']:
                        if blob.last_modified > gdb_aggregates[gdb_match]['last_modified']:
                            gdb_aggregates[gdb_match]['last_modified'] = blob.last_modified
                else:
                    # Regular file - add it directly
                    blobs.append({
                        'name': blob.name,
                        'size': blob.size,
                        'last_modified': blob.last_modified.isoformat() if blob.last_modified else None,
                        'content_type': blob.content_settings.content_type if blob.content_settings else None,
                        'etag': blob.etag,
                        'metadata': blob.metadata
                    })
                    count += 1
                    if limit and count >= limit:
                        break

            # Add aggregated .gdb entries
            for gdb_path, gdb_data in gdb_aggregates.items():
                if limit and count >= limit:
                    break
                # Convert last_modified to ISO format for consistency
                if gdb_data['last_modified']:
                    gdb_data['last_modified'] = gdb_data['last_modified'].isoformat()
                blobs.append(gdb_data)
                count += 1

            logger.debug(f"Found {len(blobs)} blobs in {container} with prefix '{prefix}' ({len(gdb_aggregates)} .gdb databases)")
            return blobs

        except Exception as e:
            logger.error(f"Failed to list blobs in {container}: {e}")
            raise

    def list_containers(self, prefix: str = None) -> List[Dict[str, Any]]:
        """
        List all containers in the storage account.

        Args:
            prefix: Optional container name prefix filter (e.g., "bronze-")

        Returns:
            List of container metadata dictionaries with name, last_modified, metadata

        Raises:
            Exception: If listing fails (propagated to caller for proper error handling)
        """
        try:
            containers = []
            logger.debug(f"Listing containers in account {self.account_name} with prefix='{prefix or ''}'")

            for container in self.blob_service.list_containers(name_starts_with=prefix):
                containers.append({
                    "name": container.name,
                    "last_modified": container.last_modified.isoformat() if container.last_modified else None,
                    "metadata": container.metadata or {}
                })

            logger.debug(f"Found {len(containers)} containers in account {self.account_name}")
            return containers

        except Exception as e:
            logger.error(f"Failed to list containers in account {self.account_name}: {e}")
            raise

    def blob_exists(self, container: str, blob_path: str) -> bool:
        """
        Check if blob exists.
        
        Args:
            container: Container name
            blob_path: Path to blob
            
        Returns:
            True if blob exists, False otherwise
        """
        try:
            container_client = self._get_container_client(container)
            blob_client = container_client.get_blob_client(blob_path)
            blob_client.get_blob_properties()
            return True
        except ResourceNotFoundError:
            return False
        except Exception as e:
            logger.error(f"Error checking blob existence: {e}")
            raise
    
    @dec_validate_container_and_blob
    def delete_blob(self, container: str, blob_path: str) -> bool:
        """
        Delete a blob.

        Container and blob existence validated automatically by decorator.

        Args:
            container: Container name
            blob_path: Path to blob

        Returns:
            True if deleted, False if not found
        """
        try:
            container_client = self._get_container_client(container)
            blob_client = container_client.get_blob_client(blob_path)
            blob_client.delete_blob()
            
            logger.info(f"Deleted blob: {container}/{blob_path}")
            return True
            
        except ResourceNotFoundError:
            logger.warning(f"Blob not found for deletion: {container}/{blob_path}")
            return False
        except Exception as e:
            logger.error(f"Failed to delete blob: {e}")
            raise

    # =========================================================================
    # BLOB ↔ MOUNT STREAMING METHODS (25 JAN 2026)
    # =========================================================================
    # These methods stream data between Azure Blob Storage and mounted filesystems
    # (e.g., Azure Files mount at /mounts/etl-temp) without loading entire files
    # into memory. Essential for processing files larger than available RAM.
    # =========================================================================

    @dec_validate_container_and_blob
    def stream_blob_to_mount(
        self,
        container: str,
        blob_path: str,
        mount_path: str,
        chunk_size_mb: int = 32,
        overwrite_existing: bool = True
    ) -> Dict[str, Any]:
        """
        Stream blob directly to mounted filesystem without loading into memory.

        Downloads blob in chunks, writing each chunk directly to disk. This avoids
        the memory spike that would occur from loading the entire file into RAM.
        Essential for processing files larger than container memory limit.

        CRITICAL: This is how we get data from blob storage ONTO the mounted
        filesystem so GDAL can process it with disk-based I/O.

        Args:
            container: Source blob container name
            blob_path: Source blob path within container
            mount_path: Destination path on mounted filesystem (MUST be absolute)
            chunk_size_mb: Size of each streaming chunk (default: 32MB)
            overwrite_existing: Whether to overwrite if file exists (default: True)

        Returns:
            Dict with transfer metrics:
                - success: bool
                - operation: "blob_to_mount"
                - bytes_transferred: int
                - duration_seconds: float
                - throughput_mbps: float
                - chunks_transferred: int
                - source_uri: str
                - destination_uri: str

        Raises:
            ValueError: If mount_path is not absolute or parent doesn't exist
            FileExistsError: If file exists and overwrite_existing=False
            ResourceNotFoundError: If blob doesn't exist

        Example:
            result = blob_repo.stream_blob_to_mount(
                container="bronze-raster",
                blob_path="tiles/flood_100yr.tif",
                mount_path="/mounts/etl-temp/input_abc123.tif"
            )
            # File now on disk at /mounts/etl-temp/input_abc123.tif
            # Memory usage: ~32MB (chunk size), not 1.8GB (file size)
        """
        import time
        from pathlib import Path

        # Validate mount_path
        mount_path_obj = Path(mount_path)
        if not mount_path_obj.is_absolute():
            raise ValueError(f"mount_path must be absolute, got: {mount_path}")
        if not mount_path_obj.parent.exists():
            raise ValueError(
                f"Mount path parent directory does not exist: {mount_path_obj.parent}. "
                f"Is the filesystem mounted?"
            )
        if mount_path_obj.exists() and not overwrite_existing:
            raise FileExistsError(f"File already exists and overwrite_existing=False: {mount_path}")

        chunk_size_bytes = chunk_size_mb * 1024 * 1024
        source_uri = f"blob://{container}/{blob_path}"
        dest_uri = f"file://{mount_path}"

        logger.info(f"📥 STREAM_BLOB_TO_MOUNT starting")
        logger.info(f"   Source: {source_uri}")
        logger.info(f"   Destination: {dest_uri}")
        logger.info(f"   Chunk size: {chunk_size_mb}MB")

        start_time = time.time()
        bytes_transferred = 0
        chunks_transferred = 0

        try:
            container_client = self._get_container_client(container)
            blob_client = container_client.get_blob_client(blob_path)

            # Get blob size for progress logging
            props = blob_client.get_blob_properties()
            blob_size = props.size
            blob_size_mb = blob_size / (1024 * 1024)
            logger.info(f"   Blob size: {blob_size_mb:.2f}MB")

            # Stream download to file
            download_stream = blob_client.download_blob()

            with open(mount_path, 'wb') as f:
                for chunk in download_stream.chunks():
                    f.write(chunk)
                    chunk_len = len(chunk)
                    bytes_transferred += chunk_len
                    chunks_transferred += 1

                    # Log progress every ~100MB
                    if chunks_transferred % max(1, int(100 / chunk_size_mb)) == 0:
                        pct = (bytes_transferred / blob_size * 100) if blob_size > 0 else 0
                        logger.info(
                            f"   Progress: {bytes_transferred / (1024*1024):.1f}MB / "
                            f"{blob_size_mb:.1f}MB ({pct:.0f}%)"
                        )

            duration = time.time() - start_time
            throughput = (bytes_transferred / (1024 * 1024)) / duration if duration > 0 else 0

            logger.info(f"📥 STREAM_BLOB_TO_MOUNT complete")
            logger.info(f"   Transferred: {bytes_transferred / (1024*1024):.2f}MB in {duration:.1f}s")
            logger.info(f"   Throughput: {throughput:.1f}MB/s")
            logger.info(f"   Chunks: {chunks_transferred}")

            return {
                'success': True,
                'operation': 'blob_to_mount',
                'bytes_transferred': bytes_transferred,
                'duration_seconds': round(duration, 2),
                'throughput_mbps': round(throughput, 2),
                'chunks_transferred': chunks_transferred,
                'chunk_size_mb': chunk_size_mb,
                'source_uri': source_uri,
                'destination_uri': dest_uri,
            }

        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"📥❌ STREAM_BLOB_TO_MOUNT failed: {e}")
            logger.error(f"   Transferred before failure: {bytes_transferred / (1024*1024):.2f}MB")

            # Clean up partial file
            if mount_path_obj.exists():
                try:
                    mount_path_obj.unlink()
                    logger.info(f"   Cleaned up partial file: {mount_path}")
                except Exception as cleanup_error:
                    logger.warning(f"   Failed to clean up partial file: {cleanup_error}")

            return {
                'success': False,
                'operation': 'blob_to_mount',
                'bytes_transferred': bytes_transferred,
                'duration_seconds': round(duration, 2),
                'throughput_mbps': 0,
                'chunks_transferred': chunks_transferred,
                'chunk_size_mb': chunk_size_mb,
                'source_uri': source_uri,
                'destination_uri': dest_uri,
                'error': str(e),
            }

    @dec_validate_container
    def stream_mount_to_blob(
        self,
        container: str,
        blob_path: str,
        mount_path: str,
        content_type: Optional[str] = None,
        chunk_size_mb: int = 32,
        overwrite_existing: bool = True,
        metadata: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Stream file from mounted filesystem to blob without loading into memory.

        Reads file in chunks, uploading each chunk directly to blob storage.
        Uses Azure SDK's upload_blob with max_concurrency for efficient streaming.
        Essential for uploading large processed files (COGs, GeoParquet).

        CRITICAL: This is how we get processed data FROM the mounted filesystem
        back to blob storage after GDAL disk-based processing.

        Args:
            container: Destination blob container name (FIRST for decorator compatibility)
            blob_path: Destination blob path within container
            mount_path: Source path on mounted filesystem (MUST exist)
            content_type: MIME type for blob (auto-detected if not specified)
            chunk_size_mb: Size of each streaming chunk (default: 32MB)
            overwrite_existing: Whether to overwrite if blob exists (default: True)
            metadata: Optional metadata dictionary for the blob

        Returns:
            Dict with transfer metrics:
                - success: bool
                - operation: "mount_to_blob"
                - bytes_transferred: int
                - duration_seconds: float
                - throughput_mbps: float
                - source_uri: str
                - destination_uri: str
                - etag: str (blob etag after upload)

        Raises:
            FileNotFoundError: If mount_path doesn't exist
            ValueError: If mount_path is a directory

        Example:
            result = blob_repo.stream_mount_to_blob(
                mount_path="/mounts/etl-temp/output_abc123.cog.tif",
                container="silver-cogs",
                blob_path="processed/flood_100yr.tif",
                content_type="image/tiff"
            )
            # COG now in blob storage
            # Memory usage: ~32MB (chunk size), not 1.8GB (file size)
        """
        import time
        from pathlib import Path

        mount_path_obj = Path(mount_path)

        # Validate source file
        if not mount_path_obj.exists():
            raise FileNotFoundError(f"Source file does not exist: {mount_path}")
        if mount_path_obj.is_dir():
            raise ValueError(f"mount_path must be a file, not a directory: {mount_path}")

        # Auto-detect content type if not specified
        if content_type is None:
            ext = mount_path_obj.suffix.lower()
            content_types = {
                '.tif': 'image/tiff',
                '.tiff': 'image/tiff',
                '.png': 'image/png',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.json': 'application/json',
                '.geojson': 'application/geo+json',
                '.parquet': 'application/vnd.apache.parquet',
            }
            content_type = content_types.get(ext, 'application/octet-stream')

        file_size = mount_path_obj.stat().st_size
        file_size_mb = file_size / (1024 * 1024)
        chunk_size_bytes = chunk_size_mb * 1024 * 1024
        source_uri = f"file://{mount_path}"
        dest_uri = f"blob://{container}/{blob_path}"

        logger.info(f"📤 STREAM_MOUNT_TO_BLOB starting")
        logger.info(f"   Source: {source_uri}")
        logger.info(f"   Destination: {dest_uri}")
        logger.info(f"   File size: {file_size_mb:.2f}MB")
        logger.info(f"   Chunk size: {chunk_size_mb}MB")
        logger.info(f"   Content-Type: {content_type}")

        start_time = time.time()

        try:
            container_client = self._get_container_client(container)
            blob_client = container_client.get_blob_client(blob_path)

            # Configure content settings
            content_settings = ContentSettings(content_type=content_type)

            # Stream upload from file - Azure SDK handles chunking internally
            # max_concurrency controls parallel chunk uploads
            with open(mount_path, 'rb') as f:
                result = blob_client.upload_blob(
                    f,
                    overwrite=overwrite_existing,
                    content_settings=content_settings,
                    metadata=metadata,
                    max_concurrency=4,  # Parallel chunk uploads
                    length=file_size,   # Helps with progress tracking
                )

            duration = time.time() - start_time
            throughput = (file_size / (1024 * 1024)) / duration if duration > 0 else 0

            logger.info(f"📤 STREAM_MOUNT_TO_BLOB complete")
            logger.info(f"   Transferred: {file_size_mb:.2f}MB in {duration:.1f}s")
            logger.info(f"   Throughput: {throughput:.1f}MB/s")
            logger.info(f"   ETag: {result.get('etag', 'N/A')}")

            return {
                'success': True,
                'operation': 'mount_to_blob',
                'bytes_transferred': file_size,
                'duration_seconds': round(duration, 2),
                'throughput_mbps': round(throughput, 2),
                'source_uri': source_uri,
                'destination_uri': dest_uri,
                'etag': result.get('etag'),
                'content_type': content_type,
            }

        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"📤❌ STREAM_MOUNT_TO_BLOB failed: {e}")

            return {
                'success': False,
                'operation': 'mount_to_blob',
                'bytes_transferred': 0,
                'duration_seconds': round(duration, 2),
                'throughput_mbps': 0,
                'source_uri': source_uri,
                'destination_uri': dest_uri,
                'error': str(e),
            }

    @dec_validate_container_and_blob
    def get_blob_properties(self, container: str, blob_path: str) -> Dict[str, Any]:
        """
        Get detailed blob properties.

        Container and blob existence validated automatically by decorator.

        Args:
            container: Container name
            blob_path: Path to blob

        Returns:
            Dict with blob properties
        """
        try:
            container_client = self._get_container_client(container)
            blob_client = container_client.get_blob_client(blob_path)
            props = blob_client.get_blob_properties()
            
            return {
                'name': props.name,
                'size': props.size,
                'last_modified': props.last_modified.isoformat() if props.last_modified else None,
                'etag': props.etag,
                'content_type': props.content_settings.content_type if props.content_settings else None,
                'metadata': props.metadata or {}
            }
            
        except Exception as e:
            logger.error(f"Failed to get blob properties: {e}")
            raise
    
    def get_blob_url_with_sas(
        self,
        container_name: str,
        blob_name: str,
        hours: int = 1,
        write: bool = False  # NOTE: Retained for future /vsiaz/ use cases; current /vsimem/ pattern doesn't use this
    ) -> str:
        """
        Generate blob URL with user delegation SAS token.

        Uses DefaultAzureCredential to generate user delegation SAS token.
        This allows managed identity access without exposing account keys.

        Args:
            container_name: Container name
            blob_name: Blob path
            hours: SAS token validity in hours (default: 1)
            write: Enable write/create permissions (default: False)
                   NOTE: Current raster COG pipeline uses /vsimem/ in-memory pattern
                   (download → /vsimem/ → process → /vsimem/ → upload) which doesn't
                   require write-enabled SAS tokens. This parameter is retained for:
                   - Future /vsiaz/ direct write use cases
                   - Other services that may need write access via GDAL VSI drivers
                   - Backward compatibility with existing code

        Returns:
            Full blob URL with SAS token appended

        Examples:
            # Read-only (default) - Used by current /vsimem/ pattern
            url = repo.get_blob_url_with_sas('bronze', 'input.tif')

            # Write-enabled for future /vsiaz/ direct write scenarios
            url = repo.get_blob_url_with_sas('silver', 'output.tif', hours=2, write=True)

        Security:
            - Uses managed identity (no account key exposure)
            - Short-lived tokens (1-4 hours typical)
            - Scoped to single blob
            - Requires 'Storage Blob Delegator' role on managed identity
        """
        try:
            permissions = "READ+WRITE" if write else "READ"
            logger.debug(f"Generating {permissions} SAS URL for {container_name}/{blob_name} (validity: {hours}h)")

            # Get blob client
            blob_client = self._get_container_client(container_name).get_blob_client(blob_name)

            # Calculate expiry time
            start_time = datetime.now(datetime.timezone.utc) if hasattr(datetime, 'timezone') else datetime.utcnow()
            expiry_time = start_time + timedelta(hours=hours)

            # Get user delegation key (works with managed identity)
            try:
                user_delegation_key = self.blob_service.get_user_delegation_key(
                    key_start_time=start_time,
                    key_expiry_time=expiry_time
                )
                logger.debug("✅ User delegation key obtained successfully")
            except Exception as e:
                logger.error(f"Failed to get user delegation key: {e}")
                raise ValueError(f"Failed to generate user delegation key. Ensure managed identity has 'Storage Blob Delegator' role: {e}")

            # Configure permissions based on write flag
            # NOTE: write=True adds write+create permissions for GDAL /vsiaz/ direct write
            # Current /vsimem/ pattern only uses read-only SAS (write=False default)
            if write:
                permissions_obj = BlobSasPermissions(read=True, write=True, create=True)
            else:
                permissions_obj = BlobSasPermissions(read=True)

            # Generate SAS token using user delegation key
            sas_token = generate_blob_sas(
                account_name=self.account_name,
                container_name=container_name,
                blob_name=blob_name,
                user_delegation_key=user_delegation_key,
                permission=permissions_obj,
                expiry=expiry_time,
                start=start_time
            )

            # Build full URL with SAS token
            blob_url = f"{blob_client.url}?{sas_token}"

            logger.debug(f"✅ SAS URL generated successfully (expires: {expiry_time.isoformat()})")
            return blob_url

        except Exception as e:
            logger.error(f"Failed to generate SAS URL for {container_name}/{blob_name}: {e}")
            raise

    def get_blob_url(self, container: str, blob_path: str) -> str:
        """
        Get public HTTPS URL for a blob (no SAS token).

        Use this for public blobs or when SAS tokens aren't needed.
        For authenticated access, use get_blob_url_with_sas() instead.

        Args:
            container: Container name
            blob_path: Blob path within container

        Returns:
            Full HTTPS URL to the blob

        Example:
            url = repo.get_blob_url('silver-cogs', 'mosaics/my_mosaic.json')
            # Returns: https://<account>.blob.core.windows.net/silver-cogs/mosaics/my_mosaic.json
        """
        return f"https://{self.account_name}.blob.core.windows.net/{container}/{blob_path}"

    # ========================================================================
    # ADVANCED OPERATIONS
    # ========================================================================

    @dec_validate_container
    def batch_download(self, container: str, blob_paths: List[str], max_workers: int = 10) -> Dict[str, BytesIO]:
        """
        Download multiple blobs in parallel.

        Container existence validated automatically by decorator.
        Individual blob validation happens per-download (via read_blob_to_stream decorator).

        Args:
            container: Container name
            blob_paths: List of blob paths to download
            max_workers: Maximum concurrent downloads

        Returns:
            Dict mapping blob paths to BytesIO streams
        """
        results = {}

        def download_single(path):
            return path, self.read_blob_to_stream(container, path)

        logger.info(f"Starting batch download of {len(blob_paths)} blobs")

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(download_single, path) for path in blob_paths]

            for future in concurrent.futures.as_completed(futures):
                try:
                    path, stream = future.result()
                    results[path] = stream
                except Exception as e:
                    logger.error(f"Failed to download blob in batch: {e}")

        logger.info(f"Batch download complete: {len(results)}/{len(blob_paths)} successful")
        return results


# ============================================================================
# FACTORY FUNCTION
# ============================================================================

def get_blob_repository() -> BlobRepository:
    """
    Factory function for dependency injection.
    
    Returns:
        BlobRepository singleton instance
    """
    return BlobRepository.instance()


# Export the main components
__all__ = ['BlobRepository', 'IBlobRepository', 'get_blob_repository']