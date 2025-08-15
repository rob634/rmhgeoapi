"""
Repository layer for Azure Table Storage and Blob Storage
Handles job tracking and blob storage operations
"""
import logging
from datetime import datetime, timezone
from typing import Optional, Dict
from azure.data.tables import TableServiceClient, TableEntity
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.identity import DefaultAzureCredential

from models import JobRequest, JobStatus
from config import Config
from logging_utils import BufferedLogger, create_buffered_logger


class JobRepository:
    """Repository for job tracking using Azure Table Storage"""
    
    def __init__(self):
        self.logger = create_buffered_logger(
            name=f"{__name__}.JobRepository",
            capacity=200,
            flush_level=logging.ERROR
        )
        
        # Prefer connection string for local dev, use managed identity for production
        if Config.AZURE_WEBJOBS_STORAGE:
            # Use connection string for local development
            self.table_service = TableServiceClient.from_connection_string(Config.AZURE_WEBJOBS_STORAGE)
        elif Config.STORAGE_ACCOUNT_NAME:
            # Use managed identity in production
            account_url = Config.get_storage_account_url('table')
            self.table_service = TableServiceClient(account_url, credential=DefaultAzureCredential())
        else:
            # No storage configuration found
            Config.validate_storage_config()
            raise ValueError("No storage configuration available")
        
        self.table_name = "jobs"
        # Don't create table at initialization - will be created when first used
    
    def _ensure_table_exists(self):
        """Create jobs table if it doesn't exist"""
        try:
            self.table_service.create_table(self.table_name)
            self.logger.info(f"Created table: {self.table_name}")
        except ResourceExistsError:
            self.logger.debug(f"Table already exists: {self.table_name}")
    
    def save_job(self, job_request: JobRequest) -> bool:
        """
        Save job request to table storage
        Returns True if new job, False if job already exists (idempotency)
        """
        try:
            self._ensure_table_exists()
            table_client = self.table_service.get_table_client(self.table_name)
            
            # Check if job already exists
            existing_job = self.get_job_status(job_request.job_id)
            if existing_job:
                self.logger.info(f"Job already exists: {job_request.job_id}")
                return False
            
            # Create table entity
            entity = TableEntity()
            entity['PartitionKey'] = 'jobs'  # All jobs in same partition for now
            entity['RowKey'] = job_request.job_id
            
            # Job data - individual fields for easy querying
            entity['dataset_id'] = job_request.dataset_id
            entity['resource_id'] = job_request.resource_id
            entity['version_id'] = job_request.version_id
            entity['operation_type'] = job_request.operation_type
            entity['system'] = job_request.system
            entity['status'] = JobStatus.PENDING
            entity['created_at'] = job_request.created_at
            entity['updated_at'] = job_request.created_at
            
            # Store complete request parameters as JSON for full tracking
            import json
            entity['request_parameters'] = json.dumps(job_request.to_dict())
            
            table_client.create_entity(entity)
            self.logger.info(f"Saved new job: {job_request.job_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error saving job {job_request.job_id}: {str(e)}")
            raise
    
    def get_job_status(self, job_id: str) -> Optional[JobStatus]:
        """Get job status by job ID"""
        try:
            self._ensure_table_exists()
            table_client = self.table_service.get_table_client(self.table_name)
            entity = table_client.get_entity('jobs', job_id)
            
            job_status = JobStatus(job_id, entity.get('status', JobStatus.PENDING))
            job_status.updated_at = entity.get('updated_at', entity.get('created_at'))
            job_status.error_message = entity.get('error_message')
            
            # Parse result_data if it exists
            result_data_str = entity.get('result_data')
            if result_data_str:
                import json
                job_status.result_data = json.loads(result_data_str)
            
            return job_status
            
        except ResourceNotFoundError:
            self.logger.warning(f"Job not found: {job_id}")
            return None
        except Exception as e:
            self.logger.error(f"Error getting job status {job_id}: {str(e)}")
            raise
    
    def update_job_status(self, job_id: str, status: str, 
                         error_message: str = None, result_data: Dict = None):
        """Update job status in table storage"""
        try:
            self._ensure_table_exists()
            table_client = self.table_service.get_table_client(self.table_name)
            
            # Get existing entity
            entity = table_client.get_entity('jobs', job_id)
            
            # Update status fields
            entity['status'] = status
            entity['updated_at'] = datetime.now(timezone.utc).isoformat()  # Get current timestamp
            
            if error_message:
                entity['error_message'] = error_message
            
            if result_data:
                import json
                entity['result_data'] = json.dumps(result_data)
            
            table_client.update_entity(entity)
            self.logger.info(f"Updated job status: {job_id} -> {status}")
            
        except ResourceNotFoundError:
            self.logger.error(f"Cannot update non-existent job: {job_id}")
            raise
        except Exception as e:
            self.logger.error(f"Error updating job status {job_id}: {str(e)}")
            raise
    
    def get_job_details(self, job_id: str) -> Optional[Dict]:
        """Get full job details including original parameters"""
        try:
            self._ensure_table_exists()
            table_client = self.table_service.get_table_client(self.table_name)
            entity = table_client.get_entity('jobs', job_id)
            
            # Convert entity to dictionary
            result = {
                'job_id': job_id,
                'dataset_id': entity.get('dataset_id'),
                'resource_id': entity.get('resource_id'),
                'version_id': entity.get('version_id'),
                'operation_type': entity.get('operation_type'),
                'system': entity.get('system', False),  # Default to False for backwards compatibility
                'status': entity.get('status'),
                'created_at': entity.get('created_at'),
                'updated_at': entity.get('updated_at'),
                'error_message': entity.get('error_message'),
            }
            
            # Parse result_data if it exists
            result_data_str = entity.get('result_data')
            if result_data_str:
                import json
                result['result_data'] = json.loads(result_data_str)
            
            # Parse and include complete request parameters if available
            request_params_str = entity.get('request_parameters')
            if request_params_str:
                import json
                result['request_parameters'] = json.loads(request_params_str)
            
            return result
            
        except ResourceNotFoundError:
            return None
        except Exception as e:
            self.logger.error(f"Error getting job details {job_id}: {str(e)}")
            raise


class StorageRepository:
    """Repository for Azure Storage operations with comprehensive blob management"""
    
    # Valid file extensions for geospatial data
    VALID_EXTENSIONS = [
        "7z", "csv", "gdb", "geojson", "geotif", "geotiff", "gpkg", 
        "json", "kml", "kmz", "osm", "shp", "tif", "tiff", "txt", 
        "xml", "zip", "parquet", "delta", "orc"
    ]
    
    def __init__(self, workspace_container_name: str = None):
        self.logger = create_buffered_logger(
            name=f"{__name__}.StorageRepository", 
            capacity=100,
            flush_level=logging.WARNING
        )
        
        # Initialize blob service client
        self._init_blob_service_client()
        
        # Set workspace container
        self.workspace_container_name = workspace_container_name or Config.BRONZE_CONTAINER_NAME
        
        # Validate workspace container exists
        if self.workspace_container_name:
            if not self.container_exists(self.workspace_container_name):
                self.logger.error(f"Workspace container {self.workspace_container_name} not found")
                raise ValueError(f"Workspace container {self.workspace_container_name} not found")
            self.logger.info(f"StorageRepository initialized with workspace container: {self.workspace_container_name}")
    
    def _init_blob_service_client(self):
        """Initialize the blob service client with authentication"""
        try:
            if Config.AZURE_WEBJOBS_STORAGE:
                # Use connection string for local development
                self.blob_service_client = BlobServiceClient.from_connection_string(Config.AZURE_WEBJOBS_STORAGE)
                self.logger.info(f"BlobServiceClient initialized with connection string")
            elif Config.STORAGE_ACCOUNT_NAME:
                # Use managed identity in production
                account_url = Config.get_storage_account_url('blob')
                self.blob_service_client = BlobServiceClient(account_url, credential=DefaultAzureCredential())
                self.logger.info(f"BlobServiceClient initialized with managed identity")
            else:
                Config.validate_storage_config()
                raise ValueError("No storage configuration available")
        except Exception as e:
            self.logger.error(f"Error initializing BlobServiceClient: {e}")
            raise
    
    def list_container_contents(self, container_name: str = None) -> Dict:
        """
        List contents of a storage container
        
        Args:
            container_name: Name of container to list (defaults to bronze container)
            
        Returns:
            Dict with container contents and metadata
        """
        try:
            from azure.storage.blob import BlobServiceClient
            
            # Use provided container or default to bronze
            if not container_name:
                container_name = Config.BRONZE_CONTAINER_NAME
            
            self.logger.info(f"Listing contents of container: {container_name}")
            
            # Get blob service client
            if Config.AZURE_WEBJOBS_STORAGE:
                # Use connection string for local development
                blob_service = BlobServiceClient.from_connection_string(Config.AZURE_WEBJOBS_STORAGE)
            elif Config.STORAGE_ACCOUNT_NAME:
                # Use managed identity in production
                account_url = Config.get_storage_account_url('blob')
                blob_service = BlobServiceClient(account_url, credential=DefaultAzureCredential())
            else:
                Config.validate_storage_config()
                raise ValueError("No storage configuration available")
            
            # Get container client
            container_client = blob_service.get_container_client(container_name)
            
            # List blobs
            blobs = []
            total_size = 0
            
            for blob in container_client.list_blobs():
                blob_info = {
                    'name': blob.name,
                    'size': blob.size,
                    'last_modified': blob.last_modified.isoformat() if blob.last_modified else None,
                    'content_type': blob.content_settings.content_type if blob.content_settings else None,
                    'etag': blob.etag,
                    'creation_time': blob.creation_time.isoformat() if blob.creation_time else None
                }
                blobs.append(blob_info)
                total_size += blob.size if blob.size else 0
            
            result = {
                'container_name': container_name,
                'blob_count': len(blobs),
                'total_size_bytes': total_size,
                'total_size_mb': round(total_size / (1024 * 1024), 2),
                'blobs': blobs
            }
            
            self.logger.info(f"Listed {len(blobs)} blobs in container {container_name}, total size: {result['total_size_mb']} MB")
            return result
            
        except Exception as e:
            self.logger.error(f"Error listing container contents: {str(e)}")
            raise
    
    def container_exists(self, container_name: str) -> bool:
        """Check if a container exists in the storage account"""
        try:
            if not isinstance(container_name, str):
                raise ValueError(f"Container name must be a string, got {type(container_name)}")
            
            self.logger.debug(f"Checking if container {container_name} exists")
            container_client = self.blob_service_client.get_container_client(container_name)
            exists = container_client.exists()
            
            if exists:
                self.logger.debug(f"Container {container_name} exists")
            else:
                self.logger.warning(f"Container {container_name} not found")
            
            return exists
            
        except Exception as e:
            self.logger.error(f"Error checking container {container_name}: {e}")
            raise
    
    def list_containers(self) -> list:
        """List all containers in the storage account"""
        try:
            container_list = self.blob_service_client.list_containers()
            names = [container.name for container in container_list]
            self.logger.info(f"Found containers: {', '.join(names)}")
            return names
        except Exception as e:
            self.logger.error(f"Error listing containers: {e}")
            raise
    
    def blob_exists(self, blob_name: str, container_name: str = None) -> bool:
        """Check if a blob exists in the specified container"""
        try:
            if not isinstance(blob_name, str):
                raise ValueError(f"Blob name must be a string, got {type(blob_name)}")
            
            container_name = container_name or self.workspace_container_name
            if not container_name:
                raise ValueError("Container name must be provided")
            
            self.logger.debug(f"Checking if blob {blob_name} exists in {container_name}")
            
            blob_client = self.blob_service_client.get_blob_client(
                container=container_name, blob=blob_name
            )
            exists = blob_client.exists()
            
            if exists:
                self.logger.debug(f"Blob {blob_name} exists in {container_name}")
            else:
                self.logger.debug(f"Blob {blob_name} not found in {container_name}")
            
            return exists
            
        except Exception as e:
            self.logger.error(f"Error checking blob {blob_name} in {container_name}: {e}")
            raise
    
    def download_blob(self, blob_name: str, container_name: str = None) -> bytes:
        """Download blob content as bytes"""
        try:
            container_name = container_name or self.workspace_container_name
            if not self.blob_exists(blob_name, container_name):
                raise ResourceNotFoundError(f"Blob {blob_name} not found in {container_name}")
            
            self.logger.debug(f"Downloading blob {blob_name} from {container_name}")
            
            blob_client = self.blob_service_client.get_blob_client(
                container=container_name, blob=blob_name
            )
            blob_data = blob_client.download_blob().readall()
            
            self.logger.info(f"Downloaded blob {blob_name} from {container_name}")
            return blob_data
            
        except Exception as e:
            self.logger.error(f"Error downloading blob {blob_name} from {container_name}: {e}")
            raise
    
    def upload_blob(self, blob_name: str, data: bytes, container_name: str = None, overwrite: bool = False) -> str:
        """Upload blob data to container"""
        try:
            container_name = container_name or self.workspace_container_name
            if not container_name:
                raise ValueError("Container name must be provided")
            
            # Validate file name and extension
            validated_name = self._validate_file_name(blob_name)
            
            self.logger.debug(f"Uploading blob {validated_name} to {container_name}")
            
            # Check if blob already exists
            if self.blob_exists(validated_name, container_name):
                if overwrite:
                    self.logger.warning(f"Overwriting existing blob {validated_name} in {container_name}")
                else:
                    raise ResourceExistsError(f"Blob {validated_name} already exists in {container_name}")
            
            blob_client = self.blob_service_client.get_blob_client(
                container=container_name, blob=validated_name
            )
            blob_client.upload_blob(data=data, overwrite=overwrite)
            
            self.logger.info(f"Uploaded blob {validated_name} to {container_name}")
            return validated_name
            
        except Exception as e:
            self.logger.error(f"Error uploading blob {blob_name} to {container_name}: {e}")
            raise
    
    def delete_blob(self, blob_name: str, container_name: str = None) -> bool:
        """Delete a blob from container"""
        try:
            container_name = container_name or self.workspace_container_name
            if not isinstance(blob_name, str):
                raise ValueError(f"Blob name must be a string, got {type(blob_name)}")
            
            if self.blob_exists(blob_name, container_name):
                blob_client = self.blob_service_client.get_blob_client(
                    container=container_name, blob=blob_name
                )
                blob_client.delete_blob()
                self.logger.info(f"Deleted blob {blob_name} from {container_name}")
                return True
            else:
                self.logger.debug(f"Blob {blob_name} does not exist in {container_name}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error deleting blob {blob_name} from {container_name}: {e}")
            raise
    
    def copy_blob(self, source_blob_name: str, dest_blob_name: str, 
                  source_container_name: str = None, dest_container_name: str = None, 
                  overwrite: bool = False) -> str:
        """Copy blob from source to destination"""
        try:
            source_container_name = source_container_name or self.workspace_container_name
            dest_container_name = dest_container_name or self.workspace_container_name
            
            # Validate source exists
            if not self.blob_exists(source_blob_name, source_container_name):
                raise ResourceNotFoundError(f"Source blob {source_blob_name} not found in {source_container_name}")
            
            # Check destination
            if self.blob_exists(dest_blob_name, dest_container_name):
                if not overwrite:
                    raise ResourceExistsError(f"Destination blob {dest_blob_name} already exists in {dest_container_name}")
                self.logger.warning(f"Overwriting {dest_blob_name} in {dest_container_name}")
            
            self.logger.debug(f"Copying {source_blob_name} from {source_container_name} to {dest_blob_name} in {dest_container_name}")
            
            # Get source blob URL
            source_blob_client = self.blob_service_client.get_blob_client(
                container=source_container_name, blob=source_blob_name
            )
            source_url = source_blob_client.url
            
            # Start copy operation
            dest_blob_client = self.blob_service_client.get_blob_client(
                container=dest_container_name, blob=dest_blob_name
            )
            dest_blob_client.start_copy_from_url(source_url)
            
            self.logger.info(f"Copy initiated: {source_container_name}/{source_blob_name} -> {dest_container_name}/{dest_blob_name}")
            return dest_blob_name
            
        except Exception as e:
            self.logger.error(f"Error copying blob: {e}")
            raise
    
    def list_blobs_with_prefix(self, prefix: str, container_name: str = None) -> list:
        """List blobs with a specific prefix"""
        try:
            container_name = container_name or self.workspace_container_name
            container_client = self.blob_service_client.get_container_client(container_name)
            
            blob_list = container_client.list_blobs(name_starts_with=prefix)
            blob_names = [blob.name for blob in blob_list]
            
            self.logger.info(f"Found {len(blob_names)} blobs with prefix '{prefix}' in {container_name}")
            return blob_names
            
        except Exception as e:
            self.logger.error(f"Error listing blobs with prefix {prefix}: {e}")
            raise
    
    def _validate_file_name(self, file_name: str) -> str:
        """Validate file name and extension"""
        try:
            if not isinstance(file_name, str):
                raise TypeError("File name must be a string")
            
            if "." not in file_name:
                raise ValueError("File name must have an extension")
            
            name_parts = file_name.split(".")
            ext = name_parts[-1].lower()
            
            if ext not in self.VALID_EXTENSIONS:
                raise ValueError(f"Invalid file extension: .{ext}. Valid extensions: {', '.join(self.VALID_EXTENSIONS)}")
            
            # Clean up multiple dots
            if len(name_parts) > 2:
                self.logger.warning(f"File name {file_name} has multiple dots, cleaning up")
                name_base = "_".join(name_parts[:-1])  # Use underscore to join parts
                validated_name = f"{name_base}.{ext}"
            else:
                validated_name = file_name
            
            self.logger.debug(f"Validated file name: {validated_name}")
            return validated_name
            
        except Exception as e:
            self.logger.error(f"Error validating file name {file_name}: {e}")
            raise