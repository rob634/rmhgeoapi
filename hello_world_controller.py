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
from schema_enforcement import SchemaDefinition

logger = get_logger(__name__)


class HelloWorldController(BaseJobController):
    """
    Multi-task hello world controller demonstrating the Job→Task architecture.
    
    Creates 'n' hello world tasks based on the request parameter, allowing for
    parallel execution and comprehensive job completion statistics.
    
    Pattern:
        1 hello_world job → n hello_world tasks (where n = 1-100)
    
    Features:
        - Configurable number of hello tasks via 'n' parameter (default: 1)
        - Individual task success/failure tracking
        - Comprehensive job completion statistics:
          * Total hellos requested
          * Hellos completed successfully
          * Hellos failed
          * Success rate percentage
          * Individual hello messages
        - Parameter validation (n must be 1-100)
        - Parallel task execution capability
    
    Request Parameters:
        - dataset_id (required): Dataset identifier
        - resource_id (required): Resource identifier
        - version_id (optional): Version identifier
        - n (optional): Number of hello tasks to create (1-100, default: 1)
        - message (optional): Base message for hello tasks
        
    Example Usage:
        # Single hello world
        POST /api/jobs/hello_world
        {
            "job_type": "hello_world",
            "dataset_id": "test",
            "resource_id": "single_hello",
            "system": true
        }
        
        # Multiple hello worlds
        POST /api/jobs/hello_world
        {
            "job_type": "hello_world",
            "dataset_id": "test",
            "resource_id": "multi_hello",
            "n": 10,
            "message": "Batch hello test",
            "system": true
        }
    """
    
    def __init__(self):
        """Initialize controller with task manager."""
        super().__init__()
        self.task_manager = TaskManager()
    
    def extend_schema(self, base_schema: SchemaDefinition) -> SchemaDefinition:
        """
        Extend base schema with HelloWorld-specific parameters.
        
        Args:
            base_schema: Base job request schema
            
        Returns:
            SchemaDefinition: Schema with hello world parameters
        """
        return base_schema \
            .optional("n", int, "Number of hello world tasks to create (1-100)") \
            .optional("message", str, "Custom message for hello world tasks")
    
    def validate_request(self, request: Dict[str, Any]) -> bool:
        """
        Validate hello world request using strict schema enforcement.
        
        Uses the new schema enforcement system for consistent validation
        with detailed error messages.
        
        Args:
            request: Request dictionary
            
        Returns:
            bool: True if valid
            
        Raises:
            SchemaValidationError: Detailed schema violation information
        """
        # Call parent validation (includes schema enforcement)
        is_valid = super().validate_request(request)
        
        # Additional HelloWorld-specific validation beyond schema
        n = request.get('n', 1)
        if n is not None:
            # Convert string to int if needed (schema allows this)
            if isinstance(n, str):
                try:
                    n = int(n)
                    request['n'] = n  # Update request
                except (ValueError, TypeError):
                    from schema_enforcement import SchemaValidationError, SchemaViolation, SchemaViolationType
                    violation = SchemaViolation(
                        type=SchemaViolationType.INVALID_TYPE,
                        parameter="n",
                        expected="integer or string-integer",
                        actual=f"string: {n}",
                        message=f"Cannot convert 'n' parameter '{n}' to integer"
                    )
                    raise SchemaValidationError([violation], "HelloWorldController.validate_request")
            
            # Range validation (more detailed than allowed_values)
            if n < 1 or n > 100:
                from schema_enforcement import SchemaValidationError, SchemaViolation, SchemaViolationType
                violation = SchemaViolation(
                    type=SchemaViolationType.INVALID_VALUE,
                    parameter="n",
                    expected="integer between 1 and 100",
                    actual=str(n),
                    message=f"'n' parameter must be between 1 and 100, got {n}"
                )
                raise SchemaValidationError([violation], "HelloWorldController.validate_request")
        
        self.logger.info(f"✅ HelloWorld request validated - will create {n} hello world tasks")
        return is_valid
    
    def create_tasks(self, job_id: str, request: Dict[str, Any]) -> List[str]:
        """
        Create n hello world tasks based on the 'n' parameter.
        
        Each task will be a separate hello world operation, allowing for
        parallel processing and individual task success/failure tracking.
        
        Args:
            job_id: Parent job ID
            request: Validated request containing 'n' parameter
            
        Returns:
            List[str]: List of task IDs (length = n)
            
        Raises:
            TaskCreationError: If any task creation fails
        """
        n = request.get('n', 1)  # Number of hello world tasks to create
        base_message = request.get('message', 'Hello from Job→Task architecture!')
        
        self.logger.info(f"Creating {n} hello world tasks for job {job_id}")
        
        task_ids = []
        failed_tasks = []
        
        for i in range(n):
            # Create task data for each hello world task
            task_data = {
                'dataset_id': request.get('dataset_id'),
                'resource_id': request.get('resource_id'),
                'version_id': request.get('version_id', 'v1'),
                'message': f"{base_message} (Hello #{i+1} of {n})",
                'hello_number': i + 1,  # Which hello this is (1-indexed)
                'total_hellos': n,      # Total number of hellos in this job
                'parent_job_id': job_id
            }
            
            # Create task with unique index
            task_id = self.task_manager.create_task(
                job_id=job_id,
                task_type='hello_world',
                task_data=task_data,
                index=i
            )
            
            if task_id:
                # Queue the task for processing
                if self.queue_task(task_id, task_data):
                    task_ids.append(task_id)
                    self.logger.debug(f"Created and queued hello_world task {i+1}/{n}: {task_id[:16]}...")
                else:
                    failed_tasks.append(i + 1)
                    self.logger.error(f"Failed to queue hello_world task {i+1}/{n}: {task_id[:16]}...")
            else:
                failed_tasks.append(i + 1)
                self.logger.error(f"Failed to create hello_world task {i+1}/{n}")
        
        # Check if we created the expected number of tasks
        if len(task_ids) == 0:
            raise TaskCreationError("Failed to create any hello_world tasks", job_id=job_id)
        elif len(task_ids) != n:
            self.logger.warning(f"Created {len(task_ids)}/{n} hello_world tasks (some failed)")
            if failed_tasks:
                self.logger.warning(f"Failed hello tasks: {failed_tasks}")
            # Continue with partial success - at least some tasks were created
        
        self.logger.info(f"Successfully created {len(task_ids)}/{n} hello_world tasks for job {job_id}")
        return task_ids
    
    def aggregate_results(self, task_results: List[Dict]) -> Dict:
        """
        Aggregate results from multiple hello world tasks.
        
        Provides comprehensive statistics about the hello world job including
        total hellos requested, completed successfully, and failed.
        
        Args:
            task_results: List of task results from all hello world tasks
            
        Returns:
            Dict: Aggregated job result with hello statistics
        """
        if not task_results:
            return {
                'status': 'no_results',
                'message': 'No hello world task results to aggregate',
                'hello_statistics': {
                    'total_hellos_requested': 0,
                    'hellos_completed_successfully': 0,
                    'hellos_failed': 0,
                    'success_rate': 0.0
                }
            }
        
        # Analyze task results to generate hello statistics
        total_hellos_requested = len(task_results)
        hellos_completed_successfully = 0
        hellos_failed = 0
        hello_messages = []
        failed_hello_numbers = []
        
        # Extract total_hellos from first task if available
        actual_total_requested = total_hellos_requested
        if task_results and isinstance(task_results[0].get('result'), dict):
            first_result = task_results[0]['result']
            if isinstance(first_result, str):
                import json
                try:
                    first_result = json.loads(first_result)
                except:
                    pass
            
            if isinstance(first_result, dict):
                actual_total_requested = first_result.get('total_hellos', total_hellos_requested)
        
        for task_result in task_results:
            task_status = task_result.get('status', 'unknown')
            task_id = task_result.get('task_id', 'unknown')
            
            if task_status == 'completed':
                hellos_completed_successfully += 1
                
                # Extract hello message if available
                result_data = task_result.get('result')
                if isinstance(result_data, str):
                    import json
                    try:
                        result_data = json.loads(result_data)
                    except:
                        result_data = {'message': result_data}
                
                if isinstance(result_data, dict):
                    hello_num = result_data.get('hello_number', len(hello_messages) + 1)
                    message = result_data.get('message', f"Hello #{hello_num}")
                    hello_messages.append(f"✅ Task {task_id[:8]}...: {message}")
                else:
                    hello_messages.append(f"✅ Task {task_id[:8]}...: Hello completed")
            else:
                hellos_failed += 1
                
                # Try to extract hello number for failed tasks
                result_data = task_result.get('result')
                if isinstance(result_data, str):
                    import json
                    try:
                        result_data = json.loads(result_data)
                        hello_num = result_data.get('hello_number', hellos_failed)
                        failed_hello_numbers.append(hello_num)
                    except:
                        pass
                
                error_msg = task_result.get('error_message', 'Unknown error')
                hello_messages.append(f"❌ Task {task_id[:8]}...: Failed - {error_msg}")
        
        # Calculate success rate
        success_rate = (hellos_completed_successfully / total_hellos_requested * 100) if total_hellos_requested > 0 else 0
        
        # Determine overall job status
        if hellos_completed_successfully == total_hellos_requested:
            overall_status = 'completed'
            overall_message = f"🎉 All {total_hellos_requested} hello world tasks completed successfully!"
        elif hellos_completed_successfully > 0:
            overall_status = 'completed_with_errors'
            overall_message = f"⚠️ {hellos_completed_successfully}/{total_hellos_requested} hello world tasks completed successfully"
        else:
            overall_status = 'failed'
            overall_message = f"❌ All {total_hellos_requested} hello world tasks failed"
        
        # Build comprehensive result
        result = {
            'status': overall_status,
            'message': overall_message,
            'hello_statistics': {
                'total_hellos_requested': actual_total_requested,
                'hellos_completed_successfully': hellos_completed_successfully,
                'hellos_failed': hellos_failed,
                'success_rate': round(success_rate, 2),
                'failed_hello_numbers': failed_hello_numbers if failed_hello_numbers else None
            },
            'task_summary': {
                'total_tasks': total_hellos_requested,
                'successful_tasks': hellos_completed_successfully,
                'failed_tasks': hellos_failed
            },
            'hello_messages': hello_messages[:10],  # First 10 messages to avoid too much data
            'sample_results': task_results[:3] if len(task_results) <= 3 else task_results[:3]  # Sample of task results
        }
        
        # Add truncation notice if there are many hellos
        if len(hello_messages) > 10:
            result['hello_messages'].append(f"... and {len(hello_messages) - 10} more hello messages")
        
        if len(task_results) > 3:
            result['additional_results_count'] = len(task_results) - 3
        
        return result