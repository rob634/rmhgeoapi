# Storage Tier Architecture - Flat vs HNS

**Date**: 25 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Define storage patterns for Bronze (flat) vs Silver (HNS) tiers

## Critical Storage Distinctions

### Bronze - Flat Blob Storage
- **No real folders** - Only virtual prefixes using `/`
- **List operations** - Must use prefix-based listing
- **No rename** - Must copy and delete
- **No atomic operations** - No true directory operations
- **Performance** - Optimized for object storage patterns

### Silver - HNS (Hierarchical Namespace) Enabled
- **Real directories** - True filesystem semantics
- **Atomic operations** - Rename, move directories
- **POSIX permissions** - But we're NOT using ACLs
- **Performance** - Optimized for analytics workloads
- **Directory operations** - Can create/delete empty directories

## Storage Repository Architecture

```python
# infrastructure/storage/base.py

from abc import ABC, abstractmethod
from enum import Enum
from typing import List, Optional, Dict, Any
from azure.storage.blob import BlobServiceClient
from azure.storage.filedatalake import DataLakeServiceClient

class StorageTier(Enum):
    BRONZE = "bronze"  # Flat blob storage
    SILVER = "silver"  # HNS-enabled (Data Lake Gen2)
    GOLD = "gold"      # HNS-enabled (future)

class StorageRepository(ABC):
    """
    Abstract base for storage operations.
    Implementations handle tier-specific differences.
    """

    @abstractmethod
    def list_files(self, path: str, recursive: bool = False) -> List[str]:
        """List files at path - handles flat vs HNS differently"""
        pass

    @abstractmethod
    def create_directory(self, path: str) -> bool:
        """Create directory - no-op for flat, real for HNS"""
        pass

    @abstractmethod
    def move_file(self, source: str, destination: str) -> bool:
        """Move/rename - copy+delete for flat, atomic for HNS"""
        pass

    @abstractmethod
    def exists(self, path: str, is_directory: bool = False) -> bool:
        """Check existence - different semantics for directories"""
        pass
```

## Bronze Storage Repository (Flat)

```python
# infrastructure/storage/bronze_repository.py

class BronzeStorageRepository(StorageRepository):
    """
    Bronze tier - flat blob storage without HNS.
    Uses virtual prefixes to simulate folders.
    """

    def __init__(self, account_name: str, container_name: str, credential):
        self.account_name = account_name
        self.container_name = container_name
        self.blob_service = BlobServiceClient(
            account_url=f"https://{account_name}.blob.core.windows.net",
            credential=credential
        )
        self.container_client = self.blob_service.get_container_client(container_name)

    def list_files(self, path: str, recursive: bool = False) -> List[str]:
        """
        List files using prefix matching.
        Bronze doesn't have real directories - uses prefixes.
        """
        # Ensure path ends with / for prefix matching
        prefix = path if path.endswith('/') else f"{path}/"

        if recursive:
            # List all blobs with prefix
            blobs = self.container_client.list_blobs(name_starts_with=prefix)
            return [blob.name for blob in blobs]
        else:
            # List only immediate "children" (simulate directory listing)
            blobs = self.container_client.list_blobs(
                name_starts_with=prefix,
                delimiter='/'  # This gives us virtual directories
            )

            files = []
            for item in blobs:
                if hasattr(item, 'name'):  # It's a blob
                    # Only include if directly in this "folder"
                    relative = item.name[len(prefix):]
                    if '/' not in relative:  # No more path separators
                        files.append(item.name)

            return files

    def create_directory(self, path: str) -> bool:
        """
        No-op for bronze - directories don't exist.
        We create a marker blob to indicate directory existence.
        """
        # Create a hidden marker file to represent the directory
        marker_path = f"{path}/.folder"
        blob_client = self.container_client.get_blob_client(marker_path)
        blob_client.upload_blob(b"", overwrite=True)
        return True

    def move_file(self, source: str, destination: str) -> bool:
        """
        Copy and delete - bronze doesn't support atomic move.
        This is NOT atomic - be careful with large files!
        """
        # Copy
        source_blob = self.container_client.get_blob_client(source)
        dest_blob = self.container_client.get_blob_client(destination)

        # Start copy operation
        copy_operation = dest_blob.start_copy_from_url(source_blob.url)

        # Wait for copy to complete (for small files)
        # For large files, you'd want to poll copy_operation['copy_status']
        import time
        while True:
            props = dest_blob.get_blob_properties()
            if props.copy.status != 'pending':
                break
            time.sleep(1)

        # Delete source only if copy succeeded
        if props.copy.status == 'success':
            source_blob.delete_blob()
            return True
        return False

    def exists(self, path: str, is_directory: bool = False) -> bool:
        """
        Check if path exists.
        For directories, check if any blobs have this prefix.
        """
        if is_directory:
            # Check if any blobs exist with this prefix
            prefix = path if path.endswith('/') else f"{path}/"
            blobs = self.container_client.list_blobs(
                name_starts_with=prefix,
                max_results=1
            )
            return any(blobs)
        else:
            # Check if specific blob exists
            blob_client = self.container_client.get_blob_client(path)
            return blob_client.exists()

    def get_url(self, path: str, sas_token: Optional[str] = None) -> str:
        """
        Get URL for blob access.
        Bronze uses blob endpoint.
        """
        base_url = f"https://{self.account_name}.blob.core.windows.net/{self.container_name}/{path}"
        if sas_token:
            return f"{base_url}?{sas_token}"
        return base_url
```

## Silver Storage Repository (HNS)

```python
# infrastructure/storage/silver_repository.py

class SilverStorageRepository(StorageRepository):
    """
    Silver tier - HNS-enabled storage (Data Lake Gen2).
    Real directories with atomic operations.
    """

    def __init__(self, account_name: str, container_name: str, credential):
        self.account_name = account_name
        self.container_name = container_name

        # Use DataLakeServiceClient for HNS operations
        self.datalake_service = DataLakeServiceClient(
            account_url=f"https://{account_name}.dfs.core.windows.net",  # Note: dfs endpoint!
            credential=credential
        )
        self.filesystem_client = self.datalake_service.get_file_system_client(container_name)

    def list_files(self, path: str, recursive: bool = False) -> List[str]:
        """
        List files using real directory operations.
        Silver has actual directories!
        """
        paths = self.filesystem_client.get_paths(path=path, recursive=recursive)

        files = []
        for path_obj in paths:
            if not path_obj.is_directory:  # Only files, not directories
                files.append(path_obj.name)

        return files

    def list_directories(self, path: str) -> List[str]:
        """
        List subdirectories - only available in HNS!
        """
        paths = self.filesystem_client.get_paths(path=path, recursive=False)

        directories = []
        for path_obj in paths:
            if path_obj.is_directory:
                directories.append(path_obj.name)

        return directories

    def create_directory(self, path: str) -> bool:
        """
        Create real directory in HNS.
        This is an actual filesystem operation!
        """
        directory_client = self.filesystem_client.get_directory_client(path)
        directory_client.create_directory()
        return True

    def move_file(self, source: str, destination: str) -> bool:
        """
        Atomic rename in HNS - this is MUCH better than bronze!
        """
        file_client = self.filesystem_client.get_file_client(source)
        file_client.rename_file(destination)
        return True

    def move_directory(self, source: str, destination: str) -> bool:
        """
        Atomic directory rename - only possible with HNS!
        This moves ALL contents atomically.
        """
        directory_client = self.filesystem_client.get_directory_client(source)
        directory_client.rename_directory(destination)
        return True

    def exists(self, path: str, is_directory: bool = False) -> bool:
        """
        Check if path exists.
        HNS can distinguish files from directories.
        """
        if is_directory:
            directory_client = self.filesystem_client.get_directory_client(path)
            return directory_client.exists()
        else:
            file_client = self.filesystem_client.get_file_client(path)
            return file_client.exists()

    def set_metadata(self, path: str, metadata: Dict[str, str]) -> bool:
        """
        Set metadata on file or directory.
        HNS supports rich metadata (but we're not using ACLs).
        """
        file_client = self.filesystem_client.get_file_client(path)
        file_client.set_metadata(metadata)
        return True

    def get_url(self, path: str, sas_token: Optional[str] = None) -> str:
        """
        Get URL for file access.
        Silver can use either blob or dfs endpoint.
        """
        # Use blob endpoint for compatibility with tools expecting blob URLs
        base_url = f"https://{self.account_name}.blob.core.windows.net/{self.container_name}/{path}"

        # Or use dfs endpoint for Data Lake specific operations
        # base_url = f"https://{self.account_name}.dfs.core.windows.net/{self.container_name}/{path}"

        if sas_token:
            return f"{base_url}?{sas_token}"
        return base_url
```

## Unified Storage Factory

```python
# infrastructure/storage/factory.py

class StorageFactory:
    """
    Factory to create appropriate storage repository based on tier.
    """

    # Configuration for each tier
    STORAGE_CONFIG = {
        StorageTier.BRONZE: {
            "account_name": "rmhazuregeo",
            "container_name": "bronze",
            "is_hns": False
        },
        StorageTier.SILVER: {
            "account_name": "rmhazuregeohns",  # Different account with HNS
            "container_name": "silver",
            "is_hns": True
        },
        StorageTier.GOLD: {
            "account_name": "rmhazuregeohns",
            "container_name": "gold",
            "is_hns": True
        }
    }

    @classmethod
    def create_repository(cls, tier: StorageTier) -> StorageRepository:
        """
        Create appropriate repository for storage tier.
        """
        config = cls.STORAGE_CONFIG[tier]
        credential = DefaultAzureCredential()  # Or use storage key

        if config["is_hns"]:
            return SilverStorageRepository(
                account_name=config["account_name"],
                container_name=config["container_name"],
                credential=credential
            )
        else:
            return BronzeStorageRepository(
                account_name=config["account_name"],
                container_name=config["container_name"],
                credential=credential
            )
```

## Usage Patterns

### Processing Pipeline Aware of Storage Tiers

```python
class DataProcessor:
    """
    Process data with awareness of storage tier differences.
    """

    def process_bronze_to_silver(self, bronze_path: str, silver_path: str):
        """
        Move processed data from Bronze (flat) to Silver (HNS).
        """
        bronze_repo = StorageFactory.create_repository(StorageTier.BRONZE)
        silver_repo = StorageFactory.create_repository(StorageTier.SILVER)

        # List files in bronze (using prefix)
        files = bronze_repo.list_files(bronze_path, recursive=True)

        # Create real directory structure in silver
        silver_repo.create_directory(silver_path)

        for file_path in files:
            # Process file
            processed_data = self.process_file(file_path)

            # Write to silver with proper directory structure
            relative_path = file_path[len(bronze_path):]
            silver_file_path = f"{silver_path}/{relative_path}"

            # Ensure parent directory exists (real directory in HNS!)
            parent_dir = "/".join(silver_file_path.split("/")[:-1])
            silver_repo.create_directory(parent_dir)

            # Write processed file
            silver_repo.write_file(silver_file_path, processed_data)
```

### Path Handling Differences

```python
class PathHandler:
    """
    Handle path differences between storage tiers.
    """

    @staticmethod
    def normalize_path(path: str, tier: StorageTier) -> str:
        """
        Normalize path based on storage tier requirements.
        """
        if tier == StorageTier.BRONZE:
            # Bronze: ensure no leading slash, use forward slashes
            path = path.lstrip('/').replace('\\', '/')
            # Don't end with slash unless it's a prefix search
            return path.rstrip('/')

        elif tier in [StorageTier.SILVER, StorageTier.GOLD]:
            # HNS: can handle directory paths properly
            path = path.replace('\\', '/')
            # Directories can end with slash
            return path

    @staticmethod
    def is_directory_path(path: str, tier: StorageTier) -> bool:
        """
        Determine if path represents a directory.
        """
        if tier == StorageTier.BRONZE:
            # In bronze, we guess based on convention
            # Directories typically end with / or have no extension
            return path.endswith('/') or '.' not in path.split('/')[-1]

        else:  # HNS tiers
            # In HNS, we can actually check
            repo = StorageFactory.create_repository(tier)
            return repo.exists(path, is_directory=True)
```

## Important Implementation Considerations

### 1. URL Formats
```python
# Bronze (flat) - blob endpoint
bronze_url = "https://rmhazuregeo.blob.core.windows.net/bronze/path/to/file.tif"

# Silver (HNS) - can use blob OR dfs endpoint
silver_blob_url = "https://rmhazuregeohns.blob.core.windows.net/silver/path/to/file.tif"
silver_dfs_url = "https://rmhazuregeohns.dfs.core.windows.net/silver/path/to/file.tif"

# For GDAL/rasterio, use blob endpoint even for HNS
vsicurl_url = f"/vsicurl/{silver_blob_url}"  # Works!
```

### 2. Performance Patterns
```python
# Bronze: Optimize for prefix scanning
def list_bronze_efficiently(prefix: str):
    # Use delimiter for virtual directories
    return container_client.walk_blobs(prefix, delimiter='/')

# Silver: Use directory operations
def list_silver_efficiently(directory: str):
    # Real directory listing is fast
    return filesystem_client.get_paths(directory, recursive=False)
```

### 3. Migration Patterns
```python
def migrate_to_hns(bronze_path: str, silver_path: str):
    """
    Migrate from flat to HNS with structure preservation.
    """
    # Bronze treats paths as prefixes
    bronze_files = bronze_repo.list_files(bronze_path, recursive=True)

    # Silver creates real directory hierarchy
    for file_path in bronze_files:
        # Extract directory structure from flat path
        parts = file_path.split('/')

        # Create nested directories in silver
        current_path = ""
        for part in parts[:-1]:  # All but filename
            current_path = f"{current_path}/{part}" if current_path else part
            silver_repo.create_directory(f"{silver_path}/{current_path}")

        # Copy file to proper location
        copy_file(file_path, f"{silver_path}/{file_path}")
```

## Benefits of This Architecture

### For Bronze (Flat):
- Simple object storage for raw uploads
- No complex permissions needed
- Cost-effective for cold data
- Works with all blob tools

### For Silver (HNS):
- Real directories for organized data
- Atomic operations for data integrity
- Better performance for analytics
- Future-ready for Delta Lake/Parquet

### For Your Platform:
- Single interface for both storage types
- Tier-aware operations
- Smooth Bronze→Silver pipeline
- No ACL complexity (as requested!)

This architecture ensures your platform correctly handles the fundamental differences between flat and HNS storage while providing a unified interface for higher-level operations!