"""
Hello World controller for testing the Job→Task architecture.

This is the simplest possible controller implementation, used to
verify the job→task pattern is working correctly.

Author: Azure Geospatial ETL Team
Version: 1.0.0
"""
from typing import List, Dict, Any

from base_controller import BaseJobController
from task_manager import TaskManager
from controller_exceptions import InvalidRequestError, TaskCreationError
from logger_setup import get_logger

logger = get_logger(__name__)


class HelloWorldController(BaseJobController):
    """
    Simple controller for hello world operations.
    
    Creates a single task that executes the HelloWorldService.
    This is the minimal implementation showing the job→task pattern.
    
    Pattern:
        1 hello_world job → 1 hello_world task
    """
    
    def __init__(self):
        """Initialize controller with task manager."""
        super().__init__()
        self.task_manager = TaskManager()
    
    def validate_request(self, request: Dict[str, Any]) -> bool:
        """
        Validate hello world request.
        
        For hello world, we just check basic required fields.
        
        Args:
            request: Request dictionary
            
        Returns:
            bool: True if valid
            
        Raises:
            InvalidRequestError: If validation fails
        """
        # Check for required fields
        if not request.get('dataset_id'):
            raise InvalidRequestError("dataset_id is required", field='dataset_id')
        
        # Resource ID can be 'none' or any value for hello world
        if 'resource_id' not in request:
            raise InvalidRequestError("resource_id is required", field='resource_id')
        
        # Operation type should be hello_world
        operation = request.get('operation_type', 'hello_world')
        if operation not in ['hello_world', 'test']:
            self.logger.warning(f"Unexpected operation type for HelloWorldController: {operation}")
        
        return True
    
    def create_tasks(self, job_id: str, request: Dict[str, Any]) -> List[str]:
        """
        Create a single hello world task.
        
        Args:
            job_id: Parent job ID
            request: Validated request
            
        Returns:
            List[str]: Single task ID
        """
        # Create task data
        task_data = {
            'operation': 'hello_world',
            'dataset_id': request.get('dataset_id'),
            'resource_id': request.get('resource_id'),
            'version_id': request.get('version_id', 'v1'),
            'message': request.get('message', 'Hello from Job→Task architecture!'),
            'parent_job_id': job_id
        }
        
        # Create single task
        task_id = self.task_manager.create_task(
            job_id=job_id,
            task_type='hello_world',
            task_data=task_data,
            index=0
        )
        
        if task_id:
            self.logger.info(f"Created hello_world task {task_id} for job {job_id}")
            return [task_id]
        else:
            raise TaskCreationError("Failed to create hello_world task", job_id=job_id)
    
    def aggregate_results(self, task_results: List[Dict]) -> Dict:
        """
        Aggregate results from hello world task.
        
        Since we only have one task, just return its result.
        
        Args:
            task_results: List with single task result
            
        Returns:
            Dict: The task result
        """
        if not task_results:
            return {
                'status': 'no_results',
                'message': 'No task results to aggregate'
            }
        
        # For single task, just return the result
        if len(task_results) == 1:
            return task_results[0]
        
        # Shouldn't happen for hello world, but handle multiple tasks
        return {
            'status': 'completed',
            'message': 'Hello world completed',
            'task_count': len(task_results),
            'tasks': task_results
        }