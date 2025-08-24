"""
Minimal state manager for Phase 0 POC
Handles job and task state tracking with Table Storage and Blob references
"""
import logging
import json
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List
from azure.data.tables import TableServiceClient, TableEntity
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceNotFoundError, ResourceExistsError
from azure.identity import DefaultAzureCredential

from config import Config
from state_models import (
    JobRecord, TaskRecord, JobState, TaskState, 
    JobType, TaskType, TaskMessage, can_transition
)
from logger_setup import get_logger

logger = get_logger(__name__)


class StateManager:
    """Manages job and task state with Table Storage and Blob references"""
    
    def __init__(self):
        # Initialize clients based on environment (managed identity vs connection string)
        if Config.STORAGE_ACCOUNT_NAME:
            # Use managed identity in Azure Functions
            table_url = Config.get_storage_account_url('table')
            blob_url = Config.get_storage_account_url('blob')
            credential = DefaultAzureCredential()
            
            self.table_service = TableServiceClient(table_url, credential=credential)
            self.blob_service = BlobServiceClient(blob_url, credential=credential)
            logger.info(f"StateManager initialized with managed identity for {Config.STORAGE_ACCOUNT_NAME}")
        elif Config.AZURE_WEBJOBS_STORAGE:
            # Fall back to connection string for local development
            self.table_service = TableServiceClient.from_connection_string(
                Config.AZURE_WEBJOBS_STORAGE
            )
            self.blob_service = BlobServiceClient.from_connection_string(
                Config.AZURE_WEBJOBS_STORAGE
            )
            logger.info("StateManager initialized with connection string (local development)")
        else:
            raise ValueError("Either STORAGE_ACCOUNT_NAME or AzureWebJobsStorage must be set")
        
        # Container for table blob references
        self.metadata_container = "geospatial-table-blobs"
        
        # Ensure tables and container exist
        self._ensure_infrastructure()
    
    def _ensure_infrastructure(self):
        """Ensure tables and container exist"""
        try:
            # Create jobs table
            self.table_service.create_table_if_not_exists("jobs")
            logger.info("Jobs table ready")
            
            # Create tasks table
            self.table_service.create_table_if_not_exists("tasks")
            logger.info("Tasks table ready")
            
            # Create metadata container
            container_client = self.blob_service.get_container_client(
                self.metadata_container
            )
            if not container_client.exists():
                container_client.create_container()
                logger.info(f"Created container: {self.metadata_container}")
                
        except Exception as e:
            logger.error(f"Error ensuring infrastructure: {e}")
            raise
    
    def create_job(self, job_record: JobRecord) -> JobRecord:
        """Create a new job record"""
        try:
            jobs_table = self.table_service.get_table_client("jobs")
            
            # Convert to entity and insert
            entity = job_record.to_entity()
            jobs_table.create_entity(entity)
            
            logger.info(f"Created job: {job_record.job_id} with status {job_record.status.value}")
            return job_record
            
        except ResourceExistsError:
            logger.warning(f"Job already exists: {job_record.job_id}")
            return self.get_job(job_record.job_id)
        except Exception as e:
            logger.error(f"Error creating job: {e}")
            raise
    
    def get_job(self, job_id: str) -> Optional[JobRecord]:
        """Get job record by ID"""
        try:
            jobs_table = self.table_service.get_table_client("jobs")
            entity = jobs_table.get_entity(partition_key="job", row_key=job_id)
            return JobRecord.from_entity(entity)
        except ResourceNotFoundError:
            logger.warning(f"Job not found: {job_id}")
            return None
        except Exception as e:
            logger.error(f"Error getting job: {e}")
            raise
    
    def update_job_status(
        self, 
        job_id: str, 
        new_status: JobState,
        error_message: Optional[str] = None
    ) -> bool:
        """Update job status with state transition validation"""
        try:
            job = self.get_job(job_id)
            if not job:
                logger.error(f"Cannot update non-existent job: {job_id}")
                return False
            
            # Validate state transition
            if not can_transition(job.status, new_status):
                logger.error(
                    f"Invalid state transition for job {job_id}: "
                    f"{job.status.value} -> {new_status.value}"
                )
                return False
            
            logger.info(f"Transitioning job {job_id} from {job.status.value} to {new_status.value}")
            
            # Update job record
            job.status = new_status
            job.updated_at = datetime.utcnow()
            
            if error_message:
                job.error_message = error_message
            
            if new_status == JobState.COMPLETED:
                job.completed_at = datetime.utcnow()
            
            # Save to table
            jobs_table = self.table_service.get_table_client("jobs")
            entity = job.to_entity()
            jobs_table.update_entity(entity, mode='replace')
            
            logger.info(f"Updated job {job_id} status to {new_status.value}")
            return True
            
        except Exception as e:
            logger.error(f"Error updating job status: {e}")
            return False
    
    def create_task(self, task_record: TaskRecord) -> TaskRecord:
        """Create a new task record"""
        try:
            tasks_table = self.table_service.get_table_client("tasks")
            
            # Set started time
            task_record.started_at = datetime.utcnow()
            
            # Convert to entity and insert
            entity = task_record.to_entity()
            tasks_table.create_entity(entity)
            
            # Update job task counters
            self._increment_job_tasks(task_record.job_id)
            
            logger.info(
                f"Created task: {task_record.task_id} "
                f"for job {task_record.job_id}"
            )
            return task_record
            
        except Exception as e:
            logger.error(f"Error creating task: {e}")
            raise
    
    def get_task(self, job_id: str, task_id: str) -> Optional[TaskRecord]:
        """Get task record by ID"""
        try:
            tasks_table = self.table_service.get_table_client("tasks")
            entity = tasks_table.get_entity(
                partition_key=job_id, 
                row_key=task_id
            )
            return TaskRecord.from_entity(entity)
        except ResourceNotFoundError:
            logger.warning(f"Task not found: {task_id}")
            return None
        except Exception as e:
            logger.error(f"Error getting task: {e}")
            raise
    
    def update_task_status(
        self,
        job_id: str,
        task_id: str,
        new_status: TaskState,
        error_message: Optional[str] = None
    ) -> bool:
        """Update task status"""
        try:
            task = self.get_task(job_id, task_id)
            if not task:
                logger.error(f"Cannot update non-existent task: {task_id}")
                return False
            
            # Update task record
            task.status = new_status
            
            if new_status == TaskState.COMPLETED:
                task.completed_at = datetime.utcnow()
                if task.started_at:
                    task.duration_seconds = (
                        task.completed_at - task.started_at
                    ).total_seconds()
                self._increment_job_completed_tasks(job_id)
                
            elif new_status == TaskState.FAILED:
                task.completed_at = datetime.utcnow()
                if error_message:
                    task.error_message = error_message
                self._increment_job_failed_tasks(job_id)
            
            # Save to table
            tasks_table = self.table_service.get_table_client("tasks")
            entity = task.to_entity()
            tasks_table.update_entity(entity, mode='replace')
            
            logger.info(f"Updated task {task_id} status to {new_status.value}")
            return True
            
        except Exception as e:
            logger.error(f"Error updating task status: {e}")
            return False
    
    def save_large_metadata(
        self,
        job_id: str,
        metadata_type: str,
        metadata: Dict[str, Any]
    ) -> str:
        """Save large metadata to blob and return reference path"""
        try:
            # Create blob path
            blob_name = f"metadata/{job_id}/{metadata_type}_{datetime.utcnow().isoformat()}.json"
            
            # Get blob client
            blob_client = self.blob_service.get_blob_client(
                container=self.metadata_container,
                blob=blob_name
            )
            
            # Upload metadata
            metadata_json = json.dumps(metadata, indent=2)
            
            # Create proper ContentSettings object
            from azure.storage.blob import ContentSettings
            content_settings = ContentSettings(content_type='application/json')
            
            blob_client.upload_blob(
                metadata_json,
                overwrite=True,
                content_settings=content_settings
            )
            
            logger.info(f"Saved metadata to blob: {blob_name}")
            return blob_name
            
        except Exception as e:
            logger.error(f"Error saving metadata to blob: {e}")
            raise
    
    def get_large_metadata(self, blob_path: str) -> Dict[str, Any]:
        """Retrieve large metadata from blob"""
        try:
            blob_client = self.blob_service.get_blob_client(
                container=self.metadata_container,
                blob=blob_path
            )
            
            # Download and parse
            blob_data = blob_client.download_blob()
            metadata = json.loads(blob_data.readall())
            
            return metadata
            
        except ResourceNotFoundError:
            logger.warning(f"Metadata blob not found: {blob_path}")
            return {}
        except Exception as e:
            logger.error(f"Error retrieving metadata: {e}")
            raise
    
    def get_job_tasks(self, job_id: str) -> List[TaskRecord]:
        """Get all tasks for a job"""
        try:
            tasks_table = self.table_service.get_table_client("tasks")
            
            # Query by partition key (job_id)
            query_filter = f"PartitionKey eq '{job_id}'"
            entities = tasks_table.query_entities(query_filter)
            
            tasks = []
            for entity in entities:
                tasks.append(TaskRecord.from_entity(entity))
            
            # Sort by sequence number
            tasks.sort(key=lambda t: t.sequence_number)
            
            return tasks
            
        except Exception as e:
            logger.error(f"Error getting job tasks: {e}")
            return []
    
    def _increment_job_tasks(self, job_id: str):
        """Increment job total tasks counter"""
        try:
            job = self.get_job(job_id)
            if job:
                job.total_tasks += 1
                jobs_table = self.table_service.get_table_client("jobs")
                entity = job.to_entity()
                jobs_table.update_entity(entity, mode='replace')
        except Exception as e:
            logger.error(f"Error incrementing job tasks: {e}")
    
    def _increment_job_completed_tasks(self, job_id: str):
        """Increment job completed tasks counter"""
        try:
            job = self.get_job(job_id)
            if job:
                job.completed_tasks += 1
                jobs_table = self.table_service.get_table_client("jobs")
                entity = job.to_entity()
                jobs_table.update_entity(entity, mode='replace')
        except Exception as e:
            logger.error(f"Error incrementing completed tasks: {e}")
    
    def _increment_job_failed_tasks(self, job_id: str):
        """Increment job failed tasks counter"""
        try:
            job = self.get_job(job_id)
            if job:
                job.failed_tasks += 1
                jobs_table = self.table_service.get_table_client("jobs")
                entity = job.to_entity()
                jobs_table.update_entity(entity, mode='replace')
        except Exception as e:
            logger.error(f"Error incrementing failed tasks: {e}")
    
    def check_job_completion(self, job_id: str) -> bool:
        """Check if all tasks are complete and update job status"""
        try:
            job = self.get_job(job_id)
            if not job:
                return False
            
            # Check if all tasks are done
            if job.completed_tasks + job.failed_tasks >= job.total_tasks:
                if job.failed_tasks > 0:
                    # Some tasks failed
                    self.update_job_status(
                        job_id, 
                        JobState.FAILED,
                        f"{job.failed_tasks} tasks failed"
                    )
                elif job.status == JobState.PROCESSING and job.completed_tasks == job.total_tasks:
                    # All tasks succeeded - mark as completed
                    logger.info(f"All {job.total_tasks} tasks completed successfully for job {job_id}, marking as COMPLETED")
                    self.update_job_status(job_id, JobState.COMPLETED)
                elif job.status not in [JobState.VALIDATING, JobState.COMPLETED, JobState.FAILED]:
                    # Other states - move to validation
                    self.update_job_status(job_id, JobState.VALIDATING)
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking job completion: {e}")
            return False