"""
Simple task router for Phase 0 POC
Routes tasks to appropriate processors using dictionary dispatch
"""
import logging
from typing import Dict, Any, Optional
from datetime import datetime
import uuid
import json
import base64

from state_models import TaskType, TaskMessage, TaskState, JobState, TaskRecord, ValidationLevel
from state_manager import StateManager
from output_validator import OutputValidator
from cog_converter import COGConverter
from config import Config, RasterConfig
from logger_setup import get_logger

logger = get_logger(__name__)


class TaskRouter:
    """Routes tasks to appropriate processors"""
    
    def __init__(self):
        self.state_manager = StateManager()
        
        # Initialize processors
        self.cog_converter = COGConverter()
        self.validator = OutputValidator()
        
        # Task type to handler mapping
        self.handlers = {
            TaskType.CREATE_COG.value: self._handle_create_cog,
            TaskType.VALIDATE.value: self._handle_validate,
            # Add more handlers as we implement them
            TaskType.ANALYZE_INPUT.value: self._handle_analyze_input,
            TaskType.PROCESS_CHUNK.value: self._handle_process_chunk,
            TaskType.ASSEMBLE_CHUNKS.value: self._handle_assemble_chunks,
            TaskType.BUILD_VRT.value: self._handle_build_vrt,
        }
    
    def route(self, task_message: TaskMessage) -> Dict[str, Any]:
        """
        Route task to appropriate handler
        
        Returns:
            Dict with processing results
        """
        logger.info(
            f"Routing task {task_message.task_id} "
            f"of type {task_message.task_type}"
        )
        
        # Update task status to processing
        self.state_manager.update_task_status(
            task_message.job_id,
            task_message.task_id,
            TaskState.PROCESSING
        )
        
        try:
            # Get handler for task type
            handler = self.handlers.get(task_message.task_type)
            
            if not handler:
                raise ValueError(f"Unknown task type: {task_message.task_type}")
            
            # Execute handler
            result = handler(task_message)
            
            # Update task status to completed
            self.state_manager.update_task_status(
                task_message.job_id,
                task_message.task_id,
                TaskState.COMPLETED
            )
            
            # For validation task, handle job completion specially
            logger.info(f"Task type: '{task_message.task_type}', checking if it's validation ('{TaskType.VALIDATE.value}')")
            if task_message.task_type == TaskType.VALIDATE.value:
                # Validation task is the final task, update job status based on validation result
                validation_passed = result.get('validation_passed', False)
                logger.info(f"Validation task result: validation_passed={validation_passed}")
                if validation_passed:
                    logger.info(f"Validation task completed successfully, marking job {task_message.job_id} as COMPLETED")
                    success = self.state_manager.update_job_status(
                        task_message.job_id,
                        JobState.COMPLETED
                    )
                    logger.info(f"Job status update to COMPLETED: {'SUCCESS' if success else 'FAILED'}")
                else:
                    logger.warning(f"Validation task found issues, job {task_message.job_id} requires review")
            else:
                # For other tasks, check if job is complete
                logger.info(f"Not a validation task, checking job completion")
                self._check_job_completion(task_message.job_id)
            
            return result
            
        except Exception as e:
            logger.error(f"Task {task_message.task_id} failed: {e}")
            
            # Update task status to failed
            self.state_manager.update_task_status(
                task_message.job_id,
                task_message.task_id,
                TaskState.FAILED,
                error_message=str(e)
            )
            
            # Update job status if needed
            self._handle_task_failure(task_message.job_id)
            
            raise
    
    def _handle_create_cog(self, task_message: TaskMessage) -> Dict[str, Any]:
        """Handle COG creation task"""
        params = task_message.parameters or {}
        
        input_path = params.get('input_path')
        output_path = params.get('output_path')
        dataset_id = params.get('dataset_id', 'rmhazuregeobronze')
        resource_id = params.get('resource_id')
        
        if not input_path or not output_path:
            raise ValueError("Missing input_path or output_path in parameters")
        
        logger.info(f"Creating COG from {input_path} to {output_path}")
        
        # Extract container and blob from paths
        # Input path format: "dataset_id/resource_id" or full path
        if '/' in input_path:
            source_container = input_path.split('/')[0]
            source_blob = '/'.join(input_path.split('/')[1:])
        else:
            source_container = dataset_id
            source_blob = resource_id or input_path
        
        # Output path format: "container/folder/job_id/output_cog.tif"
        output_parts = output_path.split('/')
        target_container = output_parts[0]
        target_blob = '/'.join(output_parts[1:])
        
        # Check if already a COG
        is_cog, _ = self.cog_converter.is_valid_cog(source_container, source_blob)
        
        if is_cog:
            logger.info(f"File {source_blob} is already a valid COG, copying to output")
            # Copy the COG directly to output location
            from azure.storage.blob import BlobServiceClient
            from azure.identity import DefaultAzureCredential
            
            if Config.STORAGE_ACCOUNT_NAME:
                blob_url = Config.get_storage_account_url('blob')
                blob_service = BlobServiceClient(blob_url, credential=DefaultAzureCredential())
            else:
                blob_service = BlobServiceClient.from_connection_string(Config.AZURE_WEBJOBS_STORAGE)
            
            # Copy blob
            source_client = blob_service.get_blob_client(source_container, source_blob)
            target_client = blob_service.get_blob_client(target_container, target_blob)
            target_client.start_copy_from_url(source_client.url)
            
            result = {
                'status': 'success',
                'output_path': output_path,
                'was_already_cog': True,
                'message': 'File was already a COG, copied to output location'
            }
        else:
            # Convert to COG
            result = self.cog_converter.convert_to_cog(
                source_container=source_container,
                source_blob=source_blob,
                dest_container=target_container,
                dest_blob=target_blob,
                cog_profile=RasterConfig.COG_PROFILE
            )
            
            result['was_already_cog'] = False
        
        # Get COG info for validation
        cog_info = self.cog_converter.get_cog_info(target_container, target_blob)
        result['metadata'] = cog_info
        
        # Queue validation task with resource info for proper naming
        self._queue_next_task(
            task_message.job_id,
            TaskType.VALIDATE,
            {
                'output_path': output_path,
                'expected_metadata': cog_info,
                'resource_id': params.get('resource_id'),  # Pass original resource name
                'version_id': params.get('version_id')     # Pass version for naming
            }
        )
        
        return result
    
    def _handle_validate(self, task_message: TaskMessage) -> Dict[str, Any]:
        """Handle validation task"""
        params = task_message.parameters or {}
        
        output_path = params.get('output_path')
        if not output_path:
            raise ValueError("Missing output_path in parameters")
        
        # Get job to check validation level
        job = self.state_manager.get_job(task_message.job_id)
        validation_level = job.validation_level if job else None
        
        logger.info(
            f"Validating output {output_path} "
            f"with level {validation_level}"
        )
        
        # Run validation with resource info for proper naming
        success, results = self.validator.validate(
            task_message.job_id,
            output_path,
            validation_level=validation_level,
            expected_metadata=params.get('expected_metadata'),
            resource_id=params.get('resource_id'),
            version_id=params.get('version_id')
        )
        
        # Add validation result to results dict
        results['validation_passed'] = success
        
        if success:
            logger.info(f"Validation succeeded for job {task_message.job_id}")
            
            # Clean up temp files
            self.validator.cleanup_temp_files(task_message.job_id)
            
            # Save final path to job record
            if results.get('final_path'):
                job = self.state_manager.get_job(task_message.job_id)
                if job:
                    job.output_path = results['final_path']
                    # Save validation results to blob
                    metadata_blob = self.state_manager.save_large_metadata(
                        task_message.job_id,
                        'validation_results',
                        results
                    )
                    job.metadata_blob = metadata_blob
                    # Update job record
                    self.state_manager.create_job(job)  # Will update existing
        else:
            # Validation failed
            logger.error(f"Validation failed for job {task_message.job_id}: {results.get('errors', [])}")
            
            # Preserve temp files for debugging
            logger.warning(
                f"Preserving temp files for failed job {task_message.job_id}"
            )
        
        return results
    
    def _handle_analyze_input(self, task_message: TaskMessage) -> Dict[str, Any]:
        """Handle input analysis task (placeholder for POC)"""
        logger.info(f"Analyzing input for job {task_message.job_id}")
        
        # For POC, just queue the next task
        params = task_message.parameters or {}
        self._queue_next_task(
            task_message.job_id,
            TaskType.CREATE_COG,
            params
        )
        
        return {'status': 'analyzed'}
    
    def _handle_process_chunk(self, task_message: TaskMessage) -> Dict[str, Any]:
        """Handle chunk processing task (placeholder for POC)"""
        logger.info(f"Processing chunk for job {task_message.job_id}")
        
        # Placeholder for chunk processing
        # In production, this would call the chunk processor
        
        return {'status': 'chunk_processed'}
    
    def _handle_assemble_chunks(self, task_message: TaskMessage) -> Dict[str, Any]:
        """Handle chunk assembly task (placeholder for POC)"""
        logger.info(f"Assembling chunks for job {task_message.job_id}")
        
        # Placeholder for chunk assembly
        # In production, this would call the assembler
        
        return {'status': 'chunks_assembled'}
    
    def _handle_build_vrt(self, task_message: TaskMessage) -> Dict[str, Any]:
        """Handle VRT building task (placeholder for POC)"""
        logger.info(f"Building VRT for job {task_message.job_id}")
        
        # Placeholder for VRT building
        # In production, this would call the VRT builder
        
        return {'status': 'vrt_built'}
    
    def _queue_next_task(
        self,
        job_id: str,
        task_type: TaskType,
        parameters: Dict[str, Any]
    ):
        """Queue the next task in the sequence"""
        from azure.storage.queue import QueueServiceClient
        import json
        import base64
        
        try:
            # Create task message
            task_id = str(uuid.uuid4())
            
            # Get current task count for sequence number
            tasks = self.state_manager.get_job_tasks(job_id)
            sequence_number = len(tasks) + 1
            
            task_message = TaskMessage(
                task_id=task_id,
                job_id=job_id,
                task_type=task_type.value,
                sequence_number=sequence_number,
                parameters=parameters
            )
            
            # Create task record
            from state_models import TaskRecord
            task_record = TaskRecord(
                task_id=task_id,
                job_id=job_id,
                status=TaskState.QUEUED,
                task_type=task_type,
                sequence_number=sequence_number,
                input_path=parameters.get('input_path', ''),
                output_path=parameters.get('output_path', '')
            )
            self.state_manager.create_task(task_record)
            
            # Queue to task queue
            from azure.storage.queue import QueueServiceClient
            from azure.identity import DefaultAzureCredential
            
            if Config.STORAGE_ACCOUNT_NAME:
                # Use managed identity in Azure Functions
                queue_url = Config.get_storage_account_url('queue')
                queue_service = QueueServiceClient(queue_url, credential=DefaultAzureCredential())
            elif Config.AZURE_WEBJOBS_STORAGE:
                # Fall back to connection string for local development
                queue_service = QueueServiceClient.from_connection_string(
                    Config.AZURE_WEBJOBS_STORAGE
                )
            else:
                raise ValueError("Either STORAGE_ACCOUNT_NAME or AzureWebJobsStorage must be set")
                
            queue_client = queue_service.get_queue_client("geospatial-tasks")
            
            # Encode message
            message_json = json.dumps(task_message.to_dict())
            message_bytes = message_json.encode('utf-8')
            message_b64 = base64.b64encode(message_bytes).decode('utf-8')
            
            queue_client.send_message(message_b64)
            
            logger.info(
                f"Queued next task: {task_type.value} "
                f"for job {job_id}"
            )
            
        except Exception as e:
            logger.error(f"Error queuing next task: {e}")
            raise
    
    def _check_job_completion(self, job_id: str):
        """Check if job is complete after task completion"""
        job_complete = self.state_manager.check_job_completion(job_id)
        
        if job_complete:
            logger.info(f"Job {job_id} has completed all tasks")
    
    def _handle_task_failure(self, job_id: str):
        """Handle task failure and update job status if needed"""
        job = self.state_manager.get_job(job_id)
        
        if job and job.failed_tasks >= 3:  # Threshold for job failure
            self.state_manager.update_job_status(
                job_id,
                JobState.FAILED,
                error_message="Too many task failures"
            )