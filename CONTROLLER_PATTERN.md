# Controller Pattern Documentation

## Quick Start: Building a New Controller

### 1. Create Your Controller Class

```python
from typing import Dict, Any, List
from base_controller import BaseJobController

class MyController(BaseJobController):
    """Controller for my operations"""
    
    def __init__(self):
        super().__init__()
        self.supported_operations = ['my_operation']
        
        # Initialize your service
        from my_service import MyService
        self.my_service = MyService()
    
    def get_supported_operations(self) -> List[str]:
        return self.supported_operations
    
    def validate_operation_parameters(self, request: Dict[str, Any]) -> bool:
        """Validate request parameters - raise InvalidRequestError if invalid"""
        operation = request.get('operation_type')
        
        if operation == 'my_operation':
            if not request.get('required_param'):
                from controller_exceptions import InvalidRequestError
                raise InvalidRequestError("required_param is missing")
        
        return True
    
    def create_tasks(self, job_id: str, request: Dict[str, Any]) -> List[str]:
        """Create tasks - return list of task IDs"""
        from repositories import TaskRepository
        import hashlib
        from datetime import datetime
        
        task_repo = TaskRepository()
        operation = request.get('operation_type')
        
        # Generate task ID
        task_id = hashlib.sha256(f"{job_id}_{operation}_0".encode()).hexdigest()
        
        # Create task record
        task_record = {
            'task_id': task_id,
            'parent_job_id': job_id,
            'task_type': 'my_task_type',
            'status': 'pending',
            'created_at': datetime.utcnow().isoformat(),
            'task_data': {
                'operation': operation,
                'parameters': request,
                'parent_job_id': job_id
            },
            'index': 0
        }
        
        success = task_repo.create_task(task_id, job_id, task_record)
        return [task_id] if success else []
    
    def aggregate_results(self, task_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Combine task results into final job result"""
        if not task_results:
            return {'status': 'error', 'error': 'No results'}
        
        # Single task - return as-is
        if len(task_results) == 1:
            return task_results[0]
        
        # Multiple tasks - combine
        return {
            'status': 'success',
            'results': task_results,
            'count': len(task_results)
        }
```

### 2. Register in Controller Factory

```python
# In controller_factory.py, add to get_controller():

elif operation_type in ['my_operation']:
    from my_controller import MyController
    controller = MyController()
    logger.info(f"Using MyController for {operation_type}")
```

### 3. Create Your Service (Task Handler)

```python
# my_service.py
from base_task_service import BaseTaskService
from typing import Dict, Any

class MyService(BaseTaskService):
    def get_supported_operations(self) -> List[str]:
        return ['my_operation']
    
    def process_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process the actual task - this runs in the queue"""
        try:
            operation = task_data.get('operation')
            parameters = task_data.get('parameters', {})
            
            if operation == 'my_operation':
                result = self._do_my_work(parameters)
                return {
                    'status': 'success',
                    'result': result,
                    'message': 'Operation completed successfully'
                }
                
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e),
                'message': 'Operation failed'
            }
    
    def _do_my_work(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        # Your actual business logic here
        return {'data': 'processed'}
```

### 4. Register Service in ServiceFactory

```python
# In services.py, add to get_service():

elif operation_type in ['my_operation']:
    from my_service import MyService
    return MyService()
```

## Key Concepts

### Request Flow
```
HTTP Request → Controller → Job → Task → Queue → Service
```

1. **Controller**: Validates, creates job/tasks
2. **Job**: Tracks overall operation status
3. **Task**: Individual work unit in queue
4. **Service**: Processes the actual work

### Parameter Types

**System Operations** (no DDH required):
```json
{"system": true, "my_param": "value"}
```

**DDH Operations** (require dataset_id, resource_id, version_id):
```json
{
  "dataset_id": "container",
  "resource_id": "file.txt", 
  "version_id": "v1",
  "my_param": "value"
}
```

### Error Handling

```python
from controller_exceptions import InvalidRequestError

# In validate_operation_parameters():
if not required_field:
    raise InvalidRequestError("required_field is missing")
```

## Usage Example

**Endpoint**: `POST /api/jobs/my_operation`

**Request**:
```json
{
  "system": true,
  "required_param": "value"
}
```

**Response**:
```json
{
  "job_id": "abc123...",
  "status": "queued",
  "message": "Job submitted successfully"
}
```

## Testing

```python
# Test your controller
from my_controller import MyController

controller = MyController()
request = {"operation_type": "my_operation", "required_param": "test"}
job_id = controller.process_job(request)
print(f"Job created: {job_id}")
```

## Files You Need

1. `my_controller.py` - Your controller class
2. `my_service.py` - Your service/task handler  
3. Update `controller_factory.py` - Register your controller
4. Update `services.py` - Register your service

## That's It!

The framework handles:
- Job/task creation and tracking
- Queue management
- Status updates
- Error handling
- Result aggregation

You just implement your business logic in the service's `process_task()` method.