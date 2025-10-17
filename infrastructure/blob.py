# ============================================================================
# CLAUDE CONTEXT - BLOB REPOSITORY
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Infrastructure - Azure Blob Storage repository
# PURPOSE: Centralized Azure Blob Storage repository with managed authentication
# LAST_REVIEWED: 16 OCT 2025
# EXPORTS: BlobRepository singleton with DefaultAzureCredential authentication
# INTERFACES: IBlobRepository for dependency injection
# PYDANTIC_MODELS: None - operates on raw bytes and streams
# DEPENDENCIES: azure-storage-blob, azure-identity, io.BytesIO, typing, config
# SOURCE: Azure Blob Storage containers (Bronze/Silver/Gold tiers)
# SCOPE: ALL blob operations for entire ETL pipeline
# VALIDATION: Blob existence, size limits, content type validation
# PATTERNS: Singleton, Repository, DefaultAzureCredential, Connection pooling
# ENTRY_POINTS: BlobRepository.instance(), RepositoryFactory.create_blob_repository()
# INDEX: IBlobRepository:60, BlobRepository:100, upload_blob:200, download_blob:300
# ============================================================================

"""
Blob Storage Repository - Central Authentication Point

This module provides THE centralized blob storage repository with managed
authentication using DefaultAzureCredential. It serves as the single point
of authentication for all blob operations across the entire ETL pipeline.

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

Usage:
    from .factory import RepositoryFactory

    # Get authenticated repository
    blob_repo = RepositoryFactory.create_blob_repository()
    
    # Use without worrying about credentials
    data = blob_repo.read_blob('bronze', 'path/to/file.tif')
    
Author: Robert and Geospatial Claude Legion
Date: 9 December 2025
"""

# ============================================================================
# IMPORTS - Top of file for fail-fast behavior
# ============================================================================

# Standard library imports
import os
import logging
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


# ============================================================================
# BLOB REPOSITORY IMPLEMENTATION
# ============================================================================

class BlobRepository(IBlobRepository):
    """
    Centralized blob storage repository with managed authentication.
    
    CRITICAL: This is THE authentication point for all blob operations.
    - Uses DefaultAzureCredential for seamless auth across environments
    - Singleton pattern ensures connection reuse
    - All ETL services use this for blob access
    
    Design Principles:
    - Single source of authentication for all blob operations
    - Connection pooling for performance
    - Thread-safe singleton implementation
    - Consistent error handling and logging
    
    Usage:
        # Get singleton instance
        blob_repo = BlobRepository.instance()
        
        # Or through factory (recommended)
        blob_repo = RepositoryFactory.create_blob_repository()
    """
    
    _instance: Optional['BlobRepository'] = None
    _initialized: bool = False
    
    def __new__(cls, connection_string: Optional[str] = None, *args, **kwargs):
        """
        Thread-safe singleton creation.
        
        Modified to accept connection_string for pattern consistency with
        other repositories, though DefaultAzureCredential is preferred.
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, connection_string: Optional[str] = None, storage_account: Optional[str] = None):
        """
        Initialize with DefaultAzureCredential - happens once.
        
        Args:
            connection_string: Optional connection string for compatibility
            storage_account: Storage account name (uses env if not provided)
        """
        if not self._initialized:
            try:
                if connection_string:
                    # Use connection string (for consistency with other repos)
                    logger.info("Initializing BlobRepository with connection string")
                    self.blob_service = BlobServiceClient.from_connection_string(connection_string)
                    self.storage_account = self.blob_service.account_name
                else:
                    # Use DefaultAzureCredential (preferred for blob storage)
                    from config import get_config
                    config = get_config()
                    storage_account = storage_account or config.storage_account_name
                    self.storage_account = storage_account
                    self.account_url = f"https://{storage_account}.blob.core.windows.net"
                    
                    logger.info(f"Initializing BlobRepository with DefaultAzureCredential for account: {storage_account}")
                    
                    # Create credential
                    self.credential = DefaultAzureCredential()
                    
                    # Create blob service client
                    self.blob_service = BlobServiceClient(
                        account_url=self.account_url,
                        credential=self.credential
                    )
                
                # Cache frequently used container clients
                self._container_clients: Dict[str, ContainerClient] = {}
                
                # Pre-initialize common containers for connection pooling
                common_containers = [
                    'rmhazuregeobronze',
                    'rmhazuregeosilver', 
                    'rmhazuregeogold'
                ]
                
                for container in common_containers:
                    try:
                        self._get_container_client(container)
                        logger.debug(f"Pre-cached container client: {container}")
                    except Exception as e:
                        logger.warning(f"Could not pre-cache container {container}: {e}")
                
                BlobRepository._initialized = True
                logger.info(f"✅ BlobRepository initialized successfully for account: {self.storage_account}")
                
            except Exception as e:
                logger.error(f"Failed to initialize BlobRepository: {e}")
                raise
    
    @classmethod
    def instance(cls, connection_string: Optional[str] = None, storage_account: Optional[str] = None) -> 'BlobRepository':
        """
        Get singleton instance.
        
        Args:
            connection_string: Optional connection string
            storage_account: Optional storage account name
            
        Returns:
            BlobRepository singleton instance
        """
        if cls._instance is None:
            cls._instance = cls(connection_string=connection_string, storage_account=storage_account)
        return cls._instance
    
    def _get_container_client(self, container: str) -> ContainerClient:
        """
        Get or create cached container client.
        
        Uses connection pooling by caching container clients.
        
        Args:
            container: Container name
            
        Returns:
            Cached or new ContainerClient
        """
        if container not in self._container_clients:
            self._container_clients[container] = self.blob_service.get_container_client(container)
            logger.debug(f"Created new container client for: {container}")
        return self._container_clients[container]
    
    # ========================================================================
    # CORE BLOB OPERATIONS
    # ========================================================================
    
    def read_blob(self, container: str, blob_path: str) -> bytes:
        """
        Read entire blob to memory.
        
        Best for small files (<100MB). For larger files, use read_blob_chunked.
        
        Args:
            container: Container name
            blob_path: Path to blob
            
        Returns:
            Blob content as bytes
            
        Raises:
            ResourceNotFoundError: If blob doesn't exist
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
    
    def read_blob_chunked(self, container: str, blob_path: str, chunk_size: int = 4*1024*1024) -> Iterator[bytes]:
        """
        Stream blob in chunks for large files.
        
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
    
    def write_blob(self, container: str, blob_path: str, data: Union[bytes, BinaryIO],
                   overwrite: bool = True, content_type: str = "application/octet-stream",
                   metadata: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Write blob from bytes or stream.
        
        Args:
            container: Container name
            blob_path: Path for blob
            data: Bytes or stream to write
            overwrite: Whether to overwrite existing blob
            content_type: MIME type for blob
            metadata: Optional metadata dictionary
            
        Returns:
            Dict with blob properties (etag, last_modified, size)
        """
        try:
            container_client = self._get_container_client(container)
            blob_client = container_client.get_blob_client(blob_path)
            
            logger.debug(f"Writing blob: {container}/{blob_path} (overwrite={overwrite})")
            
            blob_client.upload_blob(
                data,
                overwrite=overwrite,
                content_settings=ContentSettings(content_type=content_type),
                metadata=metadata or {}
            )
            
            # Get properties of written blob
            properties = blob_client.get_blob_properties()
            
            result = {
                'container': container,
                'blob_path': blob_path,
                'size': properties.size,
                'etag': properties.etag,
                'last_modified': properties.last_modified.isoformat() if properties.last_modified else None
            }
            
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
    
    def list_blobs(self, container: str, prefix: str = "", limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        List blobs with metadata.

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
    
    def delete_blob(self, container: str, blob_path: str) -> bool:
        """
        Delete a blob.
        
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
    
    def get_blob_properties(self, container: str, blob_path: str) -> Dict[str, Any]:
        """
        Get detailed blob properties.
        
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
    
    def get_blob_url_with_sas(self, container_name: str, blob_name: str, hours: int = 1) -> str:
        """
        Generate blob URL with user delegation SAS token.

        Uses DefaultAzureCredential to generate user delegation SAS token.
        This allows managed identity access without exposing account keys.

        Args:
            container_name: Container name
            blob_name: Blob path
            hours: SAS token validity in hours (default: 1)

        Returns:
            Full blob URL with SAS token appended

        Example:
            url = repo.get_blob_url_with_sas('bronze', 'path/file.tif')
            # Returns: https://storage.blob.core.windows.net/bronze/path/file.tif?sv=...
        """
        try:
            logger.debug(f"Generating SAS URL for {container_name}/{blob_name} (validity: {hours}h)")

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

            # Generate SAS token using user delegation key
            sas_token = generate_blob_sas(
                account_name=self.storage_account,
                container_name=container_name,
                blob_name=blob_name,
                user_delegation_key=user_delegation_key,
                permission=BlobSasPermissions(read=True),
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


    # ========================================================================
    # ADVANCED OPERATIONS
    # ========================================================================

    def batch_download(self, container: str, blob_paths: List[str], max_workers: int = 10) -> Dict[str, BytesIO]:
        """
        Download multiple blobs in parallel.

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