"""
Container operations controller for Job→Task architecture.

This controller handles container-related operations including listing
and synchronization, implementing the Job→Task pattern for scalable
container processing.

Operations:
    - list_container: Simple 1 job → 1 task pattern
    - sync_container: Fan-out 1 job → orchestrator → N tasks pattern

Author: Azure Geospatial ETL Team
Version: 1.0.0
"""
from typing import List, Dict, Any

from base_controller import BaseJobController
from task_manager import TaskManager
from controller_exceptions import InvalidRequestError, TaskCreationError
from logger_setup import get_logger
from schema_enforcement import SchemaDefinition

logger = get_logger(__name__)


class ContainerController(BaseJobController):
    """
    Controller for container operations.
    
    Handles two primary patterns:
    1. list_container: Simple single-task operation for inventory
    2. sync_container: Orchestrator pattern for fan-out cataloging
    
    The controller ensures proper task sequencing, especially for sync
    operations where inventory must complete before catalog tasks are created.
    """
    
    def __init__(self):
        """Initialize ContainerController with task manager."""
        super().__init__()
        self.task_manager = TaskManager()
        self.logger = get_logger(self.__class__.__name__)
    
    def extend_schema(self, base_schema: SchemaDefinition) -> SchemaDefinition:
        """
        Extend base schema with container-specific parameters.
        
        Args:
            base_schema: Base job request schema
            
        Returns:
            SchemaDefinition: Schema with container parameters
        """
        return base_schema \
            .optional("prefix", str, "Blob prefix filter for container operations") \
            .optional("recursive", bool, "Include subdirectories in container listing")
    
    def validate_request(self, request: Dict[str, Any]) -> bool:
        """
        Validate container operation request.
        
        Args:
            request: Request dictionary containing:
                - dataset_id: Container name (required)
                - resource_id: Prefix filter or 'none' (optional)
                - operation_type: 'list_container' or 'sync_container'
                
        Returns:
            bool: True if valid
            
        Raises:
            InvalidRequestError: If validation fails
        """
        # Check for required dataset_id (container name)
        if not request.get('dataset_id'):
            raise InvalidRequestError(
                "dataset_id (container name) is required",
                field='dataset_id'
            )
        
        # Validate operation type
        operation = request.get('operation_type')
        if operation not in ['list_container', 'sync_container']:
            raise InvalidRequestError(
                f"Invalid operation type: {operation}",
                field='operation_type',
                valid_values=['list_container', 'sync_container']
            )
        
        # For sync_container, version_id determines the STAC collection
        if operation == 'sync_container' and not request.get('version_id'):
            # Default to bronze-assets if not specified
            request['version_id'] = 'bronze-assets'
            self.logger.info(f"Using default collection: bronze-assets")
        
        return True
    
    def create_tasks(self, job_id: str, request: Dict[str, Any]) -> List[str]:
        """
        Create task(s) based on operation type.
        
        Routes to appropriate task creation method based on the operation:
        - list_container: Creates single listing task
        - sync_container: Creates orchestrator task (will create child tasks)
        
        Args:
            job_id: Parent job ID
            request: Validated request parameters
            
        Returns:
            List[str]: Task ID(s) created
            
        Raises:
            TaskCreationError: If task creation fails
        """
        operation = request.get('operation_type')
        
        if operation == 'list_container':
            return self._create_list_task(job_id, request)
        elif operation == 'sync_container':
            return self._create_sync_orchestrator_task(job_id, request)
        else:
            raise TaskCreationError(
                f"Unknown operation: {operation}",
                job_id=job_id
            )
    
    def _create_list_task(self, job_id: str, request: Dict[str, Any]) -> List[str]:
        """
        Create single task for container listing.
        
        Creates a task that will:
        1. List all blobs in the container
        2. Apply optional prefix filtering
        3. Run metadata inference
        4. Store compressed inventory in blob storage
        5. Return summary statistics
        
        Args:
            job_id: Parent job ID
            request: Request with dataset_id and optional resource_id
            
        Returns:
            List[str]: Single task ID in a list
        """
        # Prepare task data for listing operation
        task_data = {
            'operation': 'list_container',
            'dataset_id': request.get('dataset_id'),  # Container name
            'resource_id': request.get('resource_id', 'none'),  # Prefix filter
            'version_id': request.get('version_id', 'v1'),
            'parent_job_id': job_id,
            'task_type': 'simple'  # Single-step task
        }
        
        # Create the listing task
        task_id = self.task_manager.create_task(
            job_id=job_id,
            task_type='list_container',
            task_data=task_data,
            index=0
        )
        
        if task_id:
            self.logger.info(
                f"Created list_container task {task_id} for "
                f"container {request.get('dataset_id')}"
            )
            return [task_id]
        else:
            raise TaskCreationError(
                "Failed to create list_container task",
                job_id=job_id
            )
    
    def _create_sync_orchestrator_task(self, job_id: str, 
                                       request: Dict[str, Any]) -> List[str]:
        """
        Create orchestrator task for container synchronization.
        
        Creates an orchestrator task that will:
        1. Create fresh container inventory (runs list operation)
        2. Filter for geospatial files
        3. Create N catalog tasks (one per geospatial file)
        4. Queue all catalog tasks for parallel processing
        
        The orchestrator ensures inventory completes before creating catalog tasks,
        guaranteeing fresh data for synchronization.
        
        Args:
            job_id: Parent job ID
            request: Request with dataset_id and collection_id (version_id)
            
        Returns:
            List[str]: Single orchestrator task ID in a list
        """
        # Prepare orchestrator task data
        task_data = {
            'dataset_id': request.get('dataset_id'),  # Container to sync
            'collection_id': request.get('version_id', 'bronze-assets'),  # STAC collection
            'resource_id': request.get('resource_id', 'none'),  # Optional prefix
            'parent_job_id': job_id,
            'creates_tasks': True,  # This task will create other tasks
            'task_type': 'orchestrator'
        }
        
        # Create the orchestrator task
        task_id = self.task_manager.create_task(
            job_id=job_id,
            task_type='sync_orchestrator',
            task_data=task_data,
            index=0  # Orchestrator is always first task
        )
        
        if task_id:
            self.logger.info(
                f"Created sync_orchestrator task {task_id} for "
                f"container {request.get('dataset_id')} → "
                f"collection {task_data['collection_id']}"
            )
            return [task_id]
        else:
            raise TaskCreationError(
                "Failed to create sync_orchestrator task",
                job_id=job_id
            )
    
    def aggregate_results(self, task_results: List[Dict]) -> Dict:
        """
        Aggregate results from container operation tasks.
        
        For list_container: Returns the single task result
        For sync_container: Aggregates orchestrator and catalog task results
        
        Args:
            task_results: List of task results
            
        Returns:
            Dict: Aggregated results with operation summary
        """
        if not task_results:
            return {
                'status': 'no_results',
                'message': 'No task results to aggregate'
            }
        
        # For single task operations (list_container)
        if len(task_results) == 1:
            result = task_results[0]
            # Enhance with controller metadata
            result['controller_managed'] = True
            return result
        
        # For multi-task operations (sync_container)
        # First result is orchestrator, rest are catalog tasks
        orchestrator_result = task_results[0] if task_results else {}
        catalog_results = task_results[1:] if len(task_results) > 1 else []
        
        # Count successful catalog operations
        successful_catalogs = sum(
            1 for r in catalog_results 
            if r.get('status') == 'completed'
        )
        failed_catalogs = sum(
            1 for r in catalog_results 
            if r.get('status') == 'failed'
        )
        
        return {
            'status': 'completed' if failed_catalogs == 0 else 'completed_with_errors',
            'message': f"Container sync completed",
            'controller_managed': True,
            'orchestrator': orchestrator_result,
            'catalog_summary': {
                'total_tasks': len(catalog_results),
                'successful': successful_catalogs,
                'failed': failed_catalogs
            },
            'task_count': len(task_results)
        }