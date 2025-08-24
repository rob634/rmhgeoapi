"""
Integration module for state management system with existing function_app.py
Provides entry points for simple_cog workflow using new state management
"""
import json
import base64
import uuid
from typing import Dict, Any, Optional
from datetime import datetime

from azure.storage.queue import QueueServiceClient
from azure.identity import DefaultAzureCredential

from state_models import (
    JobState, TaskState, JobType, TaskType, 
    JobRecord, TaskRecord, TaskMessage, ValidationLevel
)
from state_manager import StateManager
from task_router import TaskRouter
from config import Config, AzureStorage
from logger_setup import get_logger

logger = get_logger(__name__)


class StateIntegration:
    """Integration layer between existing function app and new state management"""
    
    def __init__(self):
        try:
            self.state_manager = StateManager()
            self.task_router = TaskRouter()
        except Exception as e:
            logger.error(f"Failed to initialize state management: {e}")
            self.state_manager = None
            self.task_router = None
        
    def submit_simple_cog_job(
        self,
        dataset_id: str,
        resource_id: str,
        version_id: str,
        validation_level: ValidationLevel = ValidationLevel.STANDARD
    ) -> Dict[str, Any]:
        """
        Submit a simple COG conversion job using new state management
        
        This is for files < 4GB that can be processed directly
        """
        if not self.state_manager:
            raise RuntimeError("State management not initialized")
        # Generate job ID (same as existing system - SHA256 of parameters)
        import hashlib
        params_str = f"{dataset_id}_{resource_id}_{version_id}_cog_conversion"
        job_id = hashlib.sha256(params_str.encode()).hexdigest()
        
        logger.info(f"Submitting simple_cog job: {job_id}")
        
        try:
            # Create job record
            job_record = JobRecord(
                job_id=job_id,
                status=JobState.INITIALIZED,
                operation_type=JobType.SIMPLE_COG,
                input_paths=[f"{dataset_id}/{resource_id}"],
                output_path=f"{Config.SILVER_CONTAINER_NAME}/{Config.SILVER_COGS_FOLDER}/{version_id}_cog.tif",
                validation_level=validation_level
            )
            
            # Save job to state manager
            self.state_manager.create_job(job_record)
            
            # Move to PLANNING state
            self.state_manager.update_job_status(job_id, JobState.PLANNING)
            
            # For simple COG, we just need two tasks: CREATE_COG and VALIDATE
            # Queue the first task (CREATE_COG)
            self._queue_cog_task(job_id, dataset_id, resource_id, version_id)
            
            # Update job to PROCESSING
            self.state_manager.update_job_status(job_id, JobState.PROCESSING)
            
            return {
                "job_id": job_id,
                "status": "processing",
                "operation_type": "simple_cog",
                "message": "Simple COG job started with state management"
            }
            
        except Exception as e:
            logger.error(f"Error submitting simple_cog job: {e}")
            
            # Update job status to failed
            self.state_manager.update_job_status(
                job_id,
                JobState.FAILED,
                error_message=str(e)
            )
            
            raise
    
    def _queue_cog_task(
        self,
        job_id: str,
        dataset_id: str,
        resource_id: str,
        version_id: str
    ):
        """Queue a COG creation task"""
        task_id = str(uuid.uuid4())
        
        # Create task record
        task_record = TaskRecord(
            task_id=task_id,
            job_id=job_id,
            status=TaskState.QUEUED,
            task_type=TaskType.CREATE_COG,
            sequence_number=1,
            input_path=f"{dataset_id}/{resource_id}",
            output_path=f"{Config.SILVER_CONTAINER_NAME}/{Config.SILVER_TEMP_FOLDER}/{job_id}/output_cog.tif"
        )
        
        # Save task record
        self.state_manager.create_task(task_record)
        
        # Create task message
        task_message = TaskMessage(
            task_id=task_id,
            job_id=job_id,
            task_type=TaskType.CREATE_COG.value,
            sequence_number=1,
            parameters={
                'dataset_id': dataset_id,
                'resource_id': resource_id,
                'version_id': version_id,
                'input_path': f"{dataset_id}/{resource_id}",
                'output_path': task_record.output_path
            }
        )
        
        # Queue task message
        self._send_to_task_queue(task_message)
        
        logger.info(f"Queued CREATE_COG task {task_id} for job {job_id}")
    
    def _send_to_task_queue(self, task_message: TaskMessage):
        """Send task message to geospatial-tasks queue"""
        try:
            # Get queue client
            account_url = Config.get_storage_account_url('queue')
            queue_service = QueueServiceClient(
                account_url, 
                credential=DefaultAzureCredential()
            )
            queue_client = queue_service.get_queue_client("geospatial-tasks")
            
            # Encode message
            message_json = json.dumps(task_message.to_dict())
            message_bytes = message_json.encode('utf-8')
            message_b64 = base64.b64encode(message_bytes).decode('utf-8')
            
            # Send message
            queue_client.send_message(message_b64)
            
            logger.debug(f"Task message sent to queue: {task_message.task_id}")
            
        except Exception as e:
            logger.error(f"Error sending task to queue: {e}")
            raise
    
    def process_state_managed_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a task using the new state management system
        
        This is called from the task queue trigger in function_app.py
        """
        # Check if state management is initialized
        if not self.state_manager or not self.task_router:
            logger.warning("State management not initialized, cannot process state-managed task")
            return None
            
        # Check if this is a state-managed task
        if 'task_id' not in task_data or 'task_type' not in task_data:
            # Not a state-managed task, return None to let normal processing continue
            logger.debug(f"Not a state-managed task (missing task_id or task_type)")
            return None
        
        task_id = task_data.get('task_id')
        task_type = task_data.get('task_type')
        job_id = task_data.get('job_id')
        
        logger.info(f"Processing state-managed task: {task_id}")
        logger.info(f"  Task type: {task_type}")
        logger.info(f"  Job ID: {job_id}")
        logger.debug(f"  Full task data: {json.dumps(task_data)}")
        
        try:
            # Create TaskMessage from data
            logger.debug("Creating TaskMessage from data...")
            task_message = TaskMessage.from_dict(task_data)
            
            # Route to appropriate handler
            logger.info(f"Routing task {task_id} to handler for {task_type}")
            result = self.task_router.route(task_message)
            
            logger.info(f"Task {task_id} completed successfully")
            logger.debug(f"Task result: {json.dumps(result) if result else 'None'}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error processing state-managed task {task_id}: {e}", exc_info=True)
            raise
    
    def is_state_managed_job(self, operation_type: str) -> bool:
        """
        Check if an operation type should use state management
        
        For POC, only simple_cog uses state management
        """
        if not self.state_manager:
            return False
            
        if not operation_type:
            return False
            
        # List of operations that use state management
        state_managed_ops = [
            'simple_cog',
            'cog_conversion_v2',  # New version using state management
        ]
        
        return operation_type.lower() in [op.lower() for op in state_managed_ops]
    
    def get_job_status_with_state(self, job_id: str) -> Dict[str, Any]:
        """
        Get job status from state management system
        
        Returns enhanced status with task information
        """
        if not self.state_manager:
            return None
            
        job = self.state_manager.get_job(job_id)
        
        if not job:
            return None
        
        # Get tasks for this job
        tasks = self.state_manager.get_job_tasks(job_id)
        
        # Build response
        response = {
            'job_id': job.job_id,
            'status': job.status.value,
            'operation_type': job.operation_type.value,
            'created_at': job.created_at.isoformat() if job.created_at else None,
            'updated_at': job.updated_at.isoformat() if job.updated_at else None,
            'completed_at': job.completed_at.isoformat() if job.completed_at else None,
            'input_paths': job.input_paths,
            'output_path': job.output_path,
            'validation_level': job.validation_level.value,
            'progress': {
                'total_tasks': job.total_tasks,
                'completed_tasks': job.completed_tasks,
                'failed_tasks': job.failed_tasks,
                'percent_complete': (
                    int((job.completed_tasks / job.total_tasks) * 100) 
                    if job.total_tasks > 0 else 0
                )
            },
            'tasks': []
        }
        
        # Add task details
        for task in tasks:
            response['tasks'].append({
                'task_id': task.task_id,
                'task_type': task.task_type.value,
                'status': task.status.value,
                'sequence_number': task.sequence_number,
                'duration_seconds': task.duration_seconds,
                'error_message': task.error_message
            })
        
        # Add error if job failed
        if job.error_message:
            response['error_message'] = job.error_message
        
        # Get detailed metadata if available
        if job.metadata_blob:
            try:
                metadata = self.state_manager.get_large_metadata(job.metadata_blob)
                response['metadata'] = metadata
            except Exception as e:
                logger.warning(f"Could not retrieve metadata: {e}")
        
        return response