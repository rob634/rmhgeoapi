# Storage Operations Implementation Plan

**Author**: Robert and Geospatial Claude Legion  
**Date**: 13 SEP 2025  
**Status**: DESIGN PHASE  
**Purpose**: Comprehensive plan for blob storage operations in the geospatial ETL pipeline

## Executive Summary

This document outlines the implementation plan for Azure Blob Storage operations within the Job→Stage→Task architecture. It introduces centralized authentication, dynamic task orchestration patterns, and two initial job types for container operations.

## Table of Contents
1. [Architecture Overview](#architecture-overview)
2. [Blob Repository Design](#blob-repository-design)
3. [Job Types](#job-types)
4. [Dynamic Orchestration Pattern](#dynamic-orchestration-pattern)
5. [Implementation Guidelines](#implementation-guidelines)
6. [Performance Limits](#performance-limits)
7. [File Structure](#file-structure)

---

## Architecture Overview

### Core Design Principles

1. **Centralized Authentication**: BlobRepository is THE single authentication point for all blob operations
2. **Singleton Pattern**: One authenticated connection shared across entire application
3. **DefaultAzureCredential**: Seamless authentication across environments (local/Azure)
4. **Factory Integration**: Consistent with existing repository patterns

### Authentication Hierarchy

```
DefaultAzureCredential automatically tries:
1. Environment variables (AZURE_CLIENT_ID, etc.)
2. Managed Identity (in Azure)
3. Azure CLI (local development)
4. Visual Studio Code
5. Azure PowerShell
```

---

## Blob Repository Design

### repository_blob.py

```python
# ============================================================================
# CLAUDE CONTEXT - REPOSITORY
# ============================================================================
# PURPOSE: Centralized Azure Blob Storage repository with managed authentication
# EXPORTS: BlobRepository singleton with DefaultAzureCredential authentication
# INTERFACES: IBlobRepository for dependency injection
# DEPENDENCIES: azure-storage-blob, azure-identity, io.BytesIO, fsspec
# SOURCE: Azure Blob Storage containers (Bronze/Silver/Gold tiers)
# SCOPE: ALL blob operations for entire ETL pipeline
# VALIDATION: Blob existence, size limits, content type validation
# PATTERNS: Singleton, Repository, DefaultAzureCredential, connection pooling
# ENTRY_POINTS: BlobRepository.instance() for singleton access
# ============================================================================

from azure.storage.blob import BlobServiceClient, ContainerClient, BlobClient
from azure.identity import DefaultAzureCredential
from azure.core.exceptions import ResourceNotFoundError
from io import BytesIO
import fsspec
from typing import List, Dict, Any, Optional, Iterator, BinaryIO
from abc import ABC, abstractmethod
import logging
import os

logger = logging.getLogger(__name__)

class IBlobRepository(ABC):
    """Interface for blob storage operations - enables testing/mocking"""
    
    @abstractmethod
    def read_blob(self, container: str, blob_path: str) -> bytes:
        pass
    
    @abstractmethod
    def write_blob(self, container: str, blob_path: str, data: BinaryIO) -> Dict[str, Any]:
        pass
    
    @abstractmethod
    def list_blobs(self, container: str, prefix: str = "") -> List[Dict[str, Any]]:
        pass
    
    @abstractmethod
    def blob_exists(self, container: str, blob_path: str) -> bool:
        pass

class BlobRepository(IBlobRepository):
    """
    Centralized blob storage repository with managed authentication.
    
    CRITICAL: This is THE authentication point for all blob operations.
    - Uses DefaultAzureCredential for seamless auth across environments
    - Singleton pattern ensures connection reuse
    - All ETL services use this for blob access
    """
    
    _instance: Optional['BlobRepository'] = None
    _initialized: bool = False
    
    def __new__(cls, connection_string: Optional[str] = None, *args, **kwargs):
        """Modified to accept connection_string for pattern consistency"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, connection_string: Optional[str] = None, storage_account: Optional[str] = None):
        """Initialize with DefaultAzureCredential - happens once"""
        if not self._initialized:
            if connection_string:
                # Use connection string (for consistency with other repos)
                self.blob_service = BlobServiceClient.from_connection_string(connection_string)
            else:
                # Use DefaultAzureCredential (preferred for blob storage)
                storage_account = storage_account or os.environ.get('STORAGE_ACCOUNT_NAME', 'rmhazuregeo')
                self.account_url = f"https://{storage_account}.blob.core.windows.net"
                self.credential = DefaultAzureCredential()
                self.blob_service = BlobServiceClient(
                    account_url=self.account_url,
                    credential=self.credential
                )
            
            # Cache frequently used container clients
            self._container_clients: Dict[str, ContainerClient] = {}
            
            # Pre-initialize common containers
            for container in ['rmhazuregeobronze', 'rmhazuregeosilver', 'rmhazuregeogold']:
                self._get_container_client(container)
            
            BlobRepository._initialized = True
            logger.info(f"BlobRepository initialized with account: {storage_account}")
    
    @classmethod
    def instance(cls, connection_string: Optional[str] = None) -> 'BlobRepository':
        """Get singleton instance"""
        if cls._instance is None:
            cls._instance = cls(connection_string)
        return cls._instance
    
    def _get_container_client(self, container: str) -> ContainerClient:
        """Get or create cached container client"""
        if container not in self._container_clients:
            self._container_clients[container] = self.blob_service.get_container_client(container)
        return self._container_clients[container]
    
    # Core Operations
    def read_blob(self, container: str, blob_path: str) -> bytes:
        """Read entire blob to memory - for small files (<100MB)"""
        container_client = self._get_container_client(container)
        blob_client = container_client.get_blob_client(blob_path)
        return blob_client.download_blob().readall()
    
    def read_blob_to_stream(self, container: str, blob_path: str) -> BytesIO:
        """Read blob to BytesIO stream - memory efficient"""
        data = self.read_blob(container, blob_path)
        return BytesIO(data)
    
    def read_blob_chunked(self, container: str, blob_path: str, chunk_size: int = 4*1024*1024) -> Iterator[bytes]:
        """Stream blob in chunks - for large files"""
        container_client = self._get_container_client(container)
        blob_client = container_client.get_blob_client(blob_path)
        stream = blob_client.download_blob()
        for chunk in stream.chunks():
            yield chunk
    
    def write_blob(self, container: str, blob_path: str, data: BinaryIO, 
                   overwrite: bool = True, content_type: str = "application/octet-stream",
                   metadata: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Write blob from stream/BytesIO"""
        container_client = self._get_container_client(container)
        blob_client = container_client.get_blob_client(blob_path)
        blob_client.upload_blob(data, overwrite=overwrite, content_type=content_type, metadata=metadata or {})
        properties = blob_client.get_blob_properties()
        return {
            'container': container,
            'blob_path': blob_path,
            'size': properties.size,
            'etag': properties.etag,
            'last_modified': properties.last_modified.isoformat()
        }
    
    def copy_blob(self, source_container: str, source_path: str, 
                  dest_container: str, dest_path: str) -> Dict[str, Any]:
        """Server-side blob copy"""
        source_url = f"{self.account_url}/{source_container}/{source_path}"
        dest_client = self._get_container_client(dest_container).get_blob_client(dest_path)
        copy_operation = dest_client.start_copy_from_url(source_url)
        return {
            'copy_id': copy_operation['copy_id'],
            'copy_status': copy_operation['copy_status']
        }
    
    def list_blobs(self, container: str, prefix: str = "", limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """List blobs with metadata"""
        container_client = self._get_container_client(container)
        blobs = []
        count = 0
        
        for blob in container_client.list_blobs(name_starts_with=prefix):
            blobs.append({
                'name': blob.name,
                'size': blob.size,
                'last_modified': blob.last_modified.isoformat(),
                'content_type': blob.content_settings.content_type if blob.content_settings else None,
                'etag': blob.etag,
                'metadata': blob.metadata
            })
            count += 1
            if limit and count >= limit:
                break
        
        return blobs
    
    def blob_exists(self, container: str, blob_path: str) -> bool:
        """Check if blob exists"""
        try:
            container_client = self._get_container_client(container)
            blob_client = container_client.get_blob_client(blob_path)
            blob_client.get_blob_properties()
            return True
        except ResourceNotFoundError:
            return False
    
    def delete_blob(self, container: str, blob_path: str) -> bool:
        """Delete a blob"""
        try:
            container_client = self._get_container_client(container)
            blob_client = container_client.get_blob_client(blob_path)
            blob_client.delete_blob()
            return True
        except ResourceNotFoundError:
            return False
    
    def get_blob_properties(self, container: str, blob_path: str) -> Dict[str, Any]:
        """Get detailed blob properties"""
        container_client = self._get_container_client(container)
        blob_client = container_client.get_blob_client(blob_path)
        props = blob_client.get_blob_properties()
        return {
            'name': props.name,
            'size': props.size,
            'last_modified': props.last_modified.isoformat(),
            'etag': props.etag,
            'content_type': props.content_settings.content_type if props.content_settings else None,
            'metadata': props.metadata
        }
    
    # Specialized ETL Operations
    def mount_for_gdal(self, container: str) -> str:
        """Mount container for GDAL/rasterio operations"""
        fs = fsspec.filesystem('abfs',
            account_name=os.environ.get('STORAGE_ACCOUNT_NAME', 'rmhazuregeo'),
            credential=self.credential
        )
        return f"/vsiaz/{container}"
    
    def get_sas_url(self, container: str, blob_path: str, expiry_hours: int = 24) -> str:
        """Generate SAS URL for temporary external access"""
        from azure.storage.blob import generate_blob_sas, BlobSasPermissions
        from datetime import datetime, timedelta
        
        sas_token = generate_blob_sas(
            account_name=self.blob_service.account_name,
            container_name=container,
            blob_name=blob_path,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.utcnow() + timedelta(hours=expiry_hours)
        )
        return f"{self.blob_service.url}/{container}/{blob_path}?{sas_token}"
    
    def batch_download(self, container: str, blob_paths: List[str]) -> Dict[str, BytesIO]:
        """Download multiple blobs in parallel"""
        import concurrent.futures
        results = {}
        
        def download_single(path):
            return path, self.read_blob_to_stream(container, path)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(download_single, path) for path in blob_paths]
            for future in concurrent.futures.as_completed(futures):
                path, stream = future.result()
                results[path] = stream
        
        return results

def get_blob_repository() -> BlobRepository:
    """Factory function for dependency injection"""
    return BlobRepository.instance()
```

### Factory Integration

Update `repository_factory.py`:

```python
@staticmethod
def create_blob_repository(
    storage_account: Optional[str] = None,
    use_default_credential: bool = True
) -> 'BlobRepository':
    """
    Create blob storage repository with authentication.
    
    Args:
        storage_account: Storage account name (uses env if not provided)
        use_default_credential: Use DefaultAzureCredential (True) or connection string (False)
        
    Returns:
        BlobRepository singleton instance
    """
    from repository_blob import BlobRepository
    
    logger.info("🏭 Creating Blob Storage repository")
    logger.debug(f"  Storage account: {storage_account or 'from environment'}")
    logger.debug(f"  Use DefaultAzureCredential: {use_default_credential}")
    
    blob_repo = BlobRepository.instance()
    
    logger.info("✅ Blob repository created successfully")
    return blob_repo
```

---

## Job Types

### Job Type 1: summarize_container

**Purpose**: Quick container statistics and summary  
**Best For**: Small to medium containers (<5000 files)

#### Input Parameters
- `container`: Container name (required)
- `prefix`: Optional path prefix filter
- `max_files`: Maximum files to process (default: 2500)

#### Output
- Total file count
- Total size in bytes
- Largest file (name and size)
- File type distribution
- Size distribution (small/medium/large)

#### Workflow
```
Single Stage (small containers):
  → One task summarizes entire container

OR

Two Stages (large containers):
  Stage 1: Parallel listing chunks
  Stage 2: Single aggregation task
```

### Job Type 2: list_container

**Purpose**: Extract detailed metadata for each file  
**Best For**: Detailed file inventory and metadata extraction

#### Input Parameters
- `container`: Container name (required)
- `filter`: Optional search term/pattern
- `max_files`: Maximum files to process (default: 2500)
- `extract_metadata`: Level of metadata extraction (basic/full)

#### Output
- Each file gets its own task with metadata stored in `task.result_data`
- Job result contains filename→task_id mapping
- Queryable metadata catalog in tasks table

#### Workflow
```
Stage 1: Analyze & Orchestrate (single task)
  → Lists all files
  → Applies filters
  → Creates task list for Stage 2

Stage 2: Extract Metadata (parallel tasks)
  → One task per file
  → Extracts and stores metadata
  → No lineage needed (Stage 1 was planning only)

Stage 3: Create Index (optional, single task)
  → Creates filename→task_id mapping
  → Generates summary statistics
```

---

## Dynamic Orchestration Pattern

### The "Analyze & Orchestrate" Pattern

A powerful pattern where Stage 1 analyzes data and dynamically creates Stage 2 tasks based on actual content.

```
Stage 1: Single Orchestrator Task
  ↓ (analyzes data, determines work needed)
  ↓ (creates N tasks dynamically)
Stage 2: N Parallel Tasks (no lineage needed)
  ↓ (each processes independently)
Stage 3: Optional aggregation
```

### Why This Pattern is Powerful

1. **Dynamic Scaling**: Task count determined at runtime
2. **Smart Distribution**: Intelligent batching/partitioning
3. **No Wasted Tasks**: Only create tasks for actual work
4. **Metadata-Driven**: Execution strategy based on data analysis

### Implementation Example

```python
class ListContainerController(BaseController):
    """List container with dynamic task generation"""
    
    def create_stage_tasks(self, stage_number: int, job_id: str, 
                          job_parameters: Dict[str, Any],
                          previous_stage_results: Optional[Dict[str, Any]] = None) -> List[TaskDefinition]:
        
        if stage_number == 1:
            # Single orchestrator task
            return [TaskDefinition(
                task_id=self.generate_task_id(job_id, 1, "orchestrator"),
                job_type="list_container",
                task_type="analyze_and_orchestrate",
                stage_number=1,
                job_id=job_id,
                parameters={
                    'container': job_parameters['container'],
                    'filter': job_parameters.get('filter', None),
                    'max_files': job_parameters.get('max_files', 2500)
                }
            )]
            
        elif stage_number == 2:
            # Use Stage 1's results to create tasks
            orchestration_data = previous_stage_results.get('orchestration', {})
            files_to_process = orchestration_data.get('files', [])
            
            tasks = []
            for file_info in files_to_process:
                task_id = self.generate_task_id(job_id, 2, 
                    f"file-{hashlib.md5(file_info['path'].encode()).hexdigest()[:8]}")
                
                tasks.append(TaskDefinition(
                    task_id=task_id,
                    job_type="list_container",
                    task_type="extract_metadata",
                    stage_number=2,
                    job_id=job_id,
                    parameters={
                        'container': job_parameters['container'],
                        'file_path': file_info['path'],
                        'file_size': file_info['size']
                    }
                ))
            
            return tasks
```

### Other Jobs Using This Pattern

1. **process_raster**: Analyze raster → Create tiles
2. **validate_upload**: Analyze upload → Validate batches
3. **migrate_data**: Query source → Migrate chunks
4. **scan_changes**: Compare snapshots → Process changes
5. **extract_features**: Analyze dataset → Extract layers

---

## Implementation Guidelines

### Service Usage Pattern

```python
# In any service or controller
from repository_factory import RepositoryFactory

def my_service_function():
    # Get authenticated blob repository
    blob_repo = RepositoryFactory.create_blob_repository()
    
    # Use it without worrying about credentials
    data = blob_repo.read_blob('bronze', 'path/to/file.tif')
    
    # All operations are authenticated
    blobs = blob_repo.list_blobs('silver', prefix='processed/')
```

### Task Handler Pattern

```python
@TaskRegistry.instance().register("extract_metadata")
def create_metadata_handler():
    """Extract metadata for a single file"""
    def handle_metadata(params: Dict[str, Any], context: TaskContext) -> Dict[str, Any]:
        blob_repo = RepositoryFactory.create_blob_repository()
        
        # Get file properties
        props = blob_repo.get_blob_properties(
            params['container'], 
            params['file_path']
        )
        
        # Extract additional metadata based on file type
        metadata = {
            'basic': props,
            'extracted': extract_custom_metadata(props)
        }
        
        return metadata
    
    return handle_metadata
```

---

## Performance Limits

### Azure Functions Constraints

| Plan Type | Default Timeout | Max Timeout | Recommended File Limit |
|-----------|----------------|-------------|------------------------|
| Consumption | 5 minutes | 10 minutes | 1000 files |
| Premium | 30 minutes | Unlimited* | 5000 files |
| Dedicated | 30 minutes | Unlimited* | 10000 files |

*Unlimited with appropriate configuration

### Safe Operating Limits

```python
class ContainerSizeLimits:
    """Safe limits for single-function execution"""
    
    # Conservative limits
    SAFE_FILE_COUNT = 1000        # < 30 seconds
    STANDARD_FILE_COUNT = 2500     # < 90 seconds  
    MAX_FILE_COUNT = 5000          # < 3 minutes
    
    # Development limits
    DEV_FILE_COUNT = 500           # Quick testing
```

### Overflow Handling

```python
def handle_orchestrate(params: Dict[str, Any], context: TaskContext) -> Dict[str, Any]:
    MAX_FILES = params.get('max_files', 2500)
    HARD_LIMIT = 5000
    
    blobs = blob_repo.list_blobs(container, prefix, limit=HARD_LIMIT + 1)
    blob_count = len(blobs)
    
    if blob_count > HARD_LIMIT:
        raise NotImplementedError(
            f"Container '{container}' has {blob_count} files (limit: {HARD_LIMIT}). "
            f"This exceeds single-function capacity. "
            f"Consider: 1) Using a more specific filter, "
            f"2) Processing a subfolder, or "
            f"3) Waiting for multi-stage orchestration support."
        )
```

### Performance Estimates

| Operation | Time per Item | 1000 Items | 5000 Items |
|-----------|--------------|------------|------------|
| List blob | 0.5ms | 0.5s | 2.5s |
| Create task | 25ms | 25s | 125s |
| Queue message | 10ms | 10s | 50s |
| DB insert | 5ms | 5s | 25s |
| **Total** | ~40ms | ~40s | ~200s |

---

## File Structure

### New Files to Create

```
rmhgeoapi/
├── repository_blob.py           # Blob storage repository (singleton)
├── service_blob.py              # Blob operation task handlers
├── controller_container.py      # Container operations controllers
├── schema_blob.py              # Blob-specific data models
└── STORAGE_OPERATIONS_PLAN.md  # This document
```

### Modified Files

```
repository_factory.py            # Add create_blob_repository() method
```

---

## Implementation Phases

### Phase 1: Core Infrastructure (Current)
- [x] Design blob repository with DefaultAzureCredential
- [x] Define container operation job types
- [x] Design dynamic orchestration pattern
- [ ] Implement repository_blob.py
- [ ] Update repository_factory.py

### Phase 2: Basic Operations
- [ ] Implement summarize_container job
- [ ] Implement list_container job
- [ ] Create service_blob.py handlers
- [ ] Test with small containers

### Phase 3: Advanced Features
- [ ] Add GDAL mounting support
- [ ] Implement batch operations
- [ ] Add SAS URL generation
- [ ] Performance optimization

### Phase 4: Scale & Polish
- [ ] Multi-stage orchestration for large containers
- [ ] Caching layer for frequently accessed blobs
- [ ] Monitoring and metrics
- [ ] Production hardening

---

## Key Design Decisions

1. **Singleton BlobRepository**: Single authenticated connection for entire app
2. **DefaultAzureCredential**: Seamless auth across environments
3. **Dynamic Task Creation**: Stage 1 analyzes, Stage 2 executes
4. **Task-per-File**: Leverages tasks table as metadata store
5. **Conservative Limits**: 2500 files default, 5000 max, NotImplementedError beyond

---

## Success Metrics

- ✅ All blob operations use centralized authentication
- ✅ No credential management in services/controllers
- ✅ Container operations complete within timeout limits
- ✅ Metadata queryable via tasks table
- ✅ Clear errors for oversized containers

---

*This plan provides a complete implementation roadmap for blob storage operations within the Job→Stage→Task architecture, emphasizing centralized authentication, dynamic orchestration, and scalable parallel processing.*