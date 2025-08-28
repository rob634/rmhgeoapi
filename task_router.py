"""
Clean task router for Job→Task architecture
Routes tasks to appropriate handlers using string dispatch pattern
"""
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from logger_setup import get_logger

# DEPRECATED: Old state management imports removed
# from state_models import TaskType, TaskMessage, TaskState, JobState, TaskRecord, ValidationLevel
# from state_manager import StateManager
# from output_validator import OutputValidator
# from cog_converter import COGConverter

logger = get_logger(__name__)


class TaskRouter:
    """Clean task router for Job→Task architecture"""
    
    def __init__(self):
        logger.info("Initializing clean TaskRouter for Job→Task architecture")
        
        # Import TaskManager for task completion workflow
        from task_manager import TaskManager
        self.task_manager = TaskManager()
        
        # CLEAN Job→Task architecture handlers only
        self.handlers = {
            'hello_world': self._handle_hello_world,
            # Add new Job→Task handlers here:
            # 'catalog_file': self._handle_catalog_file,
            # 'sync_orchestrator': self._handle_sync_orchestrator,
        }
    
    def route(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Route task to appropriate handler using clean Job→Task architecture
        
        Args:
            task_data: Task data dictionary from queue message
            
        Returns:
            Dict with processing results
        """
        task_id = task_data.get('task_id', 'unknown')
        task_type = task_data.get('task_type', 'unknown')
        job_id = task_data.get('job_id', 'unknown')
        
        logger.info(f"Routing task {task_id} of type '{task_type}' for job {job_id}")
        
        try:
            # Update task status to processing
            self.task_manager.update_task_status(task_id, 'processing')
            
            # Get handler for task type
            handler = self.handlers.get(task_type)
            
            if not handler:
                available_types = list(self.handlers.keys())
                logger.error(f"Unknown task type: '{task_type}'. Available types: {available_types}")
                # Mark task as failed
                self.task_manager.update_task_status(task_id, 'failed', 
                    {'error': f"Unknown task type: {task_type}"})
                raise ValueError(f"Unknown task type: {task_type}")
            
            # Execute handler with task data
            logger.info(f"Executing handler for task type '{task_type}'")
            result = handler(task_data)
            
            # Mark task as completed and store result
            self.task_manager.update_task_status(task_id, 'completed', 
                {'result': result})
            
            logger.info(f"Task {task_id} completed successfully")
            return result
            
        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}", exc_info=True)
            # Mark task as failed with error details
            self.task_manager.update_task_status(task_id, 'failed', 
                {'error': str(e)})
            raise
    
# DEPRECATED: All old state-managed handlers removed for clean architecture
# Old handlers: _handle_create_cog, _handle_validate, _handle_analyze_input, 
# _handle_process_chunk, _handle_assemble_chunks, _handle_build_vrt
# 
# Clean Job→Task architecture uses controllers and services instead
    
    def _handle_hello_world(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle hello world task from clean Job→Task architecture"""
        task_id = task_data.get('task_id', 'unknown')
        job_id = task_data.get('job_id', 'unknown')
        
        logger.info(f"Processing hello world task {task_id}")
        
        # Extract hello world parameters from task data
        message = task_data.get('message', 'Hello from Clean Task Router!')
        hello_number = task_data.get('hello_number', 1)
        total_hellos = task_data.get('total_hellos', 1)
        dataset_id = task_data.get('dataset_id', 'unknown')
        resource_id = task_data.get('resource_id', 'unknown')
        
        logger.info(
            f"Hello World #{hello_number}/{total_hellos}: {message} "
            f"(Dataset: {dataset_id}, Resource: {resource_id})"
        )
        
        # Build result data
        result = {
            'status': 'success',
            'message': message,
            'hello_number': hello_number,
            'total_hellos': total_hellos,
            'dataset_id': dataset_id,
            'resource_id': resource_id,
            'task_id': task_id,
            'job_id': job_id,
            'processed_at': datetime.now().isoformat(),
            'greeting': f"🎉 Hello #{hello_number} completed successfully!"
        }
        
        logger.info(f"Hello world task {task_id} completed: {result['greeting']}")
        
        return result
    
# DEPRECATED: All old state management methods removed
# Clean Job→Task architecture doesn't need complex state transitions
# Task results are aggregated by controllers, not by TaskRouter