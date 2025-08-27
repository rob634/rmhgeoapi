# Task Processing Debug Guide

**Purpose**: Comprehensive guide for debugging Azure Functions task processing issues
**Context**: 7-Hello test investigation - tasks going to poison queue
**Last Updated**: August 27, 2025

## 🚨 Current Issue

**Problem**: Tasks consistently moved to poison queue immediately after creation
**Impact**: Job→Task architecture cannot complete, blocking multi-task operations
**Status**: Enhanced error logging deployed, awaiting Azure Functions log analysis

## 🔧 Debug Tools Available

### 1. Enhanced Error Logging (DEPLOYED)
Location: `function_app.py:1380-1458`

Captures detailed errors around:
- Service retrieval (`ServiceFactory.get_service()`)
- Service processing (`service.process()`)  
- Task status updates (`task_repo.update_task_status()`)
- Job completion checks (`task_manager.check_job_completion()`)

### 2. Local Testing Framework
Use this to isolate issues:

```python
# Test service retrieval
from services import ServiceFactory
service = ServiceFactory.get_service('hello_world')

# Test service processing with exact task data
task_data = {
    'task_id': 'test_task_123',
    'parent_job_id': 'test_job_456', 
    'operation': 'hello_world',
    'dataset_id': 'test_dataset',
    'resource_id': 'test_resource',
    'version_id': 'v1',
    'message': 'Test message'
}

# Test parameter passing (FIXED)
excluded_params = ['task_id', 'operation', 'parent_job_id', 'dataset_id', 'resource_id', 'version_id']
additional_params = {k: v for k, v in task_data.items() if k not in excluded_params}

result = service.process(
    job_id=task_data['task_id'],
    dataset_id=task_data.get('dataset_id'),
    resource_id=task_data.get('resource_id'),
    version_id=task_data.get('version_id', 'v1'),
    operation_type='hello_world',
    **additional_params
)
```

### 3. Poison Queue Monitoring
```python
# Check poison queue status
response = requests.get('https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/monitor/poison')

# Clear poison queue and check for error details  
clear_response = requests.post('https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/monitor/poison')
```

## 🎯 Debugging Methodology

### Phase 1: Identify Error Location
Enhanced logging will show which component fails:

1. **Service Retrieval Error**:
   - Look for: "CRITICAL: Service retrieval failed"
   - Likely cause: Import failures, ServiceFactory issues
   - Fix: Check import paths, module dependencies

2. **Service Processing Error**:
   - Look for: "CRITICAL: Service.process() failed"  
   - Likely cause: Parameter issues, service logic errors
   - Fix: Validate parameter passing, check service implementation

3. **Task Status Update Error**:
   - Look for: "CRITICAL: Task status update failed"
   - Likely cause: Repository access issues, Table Storage problems
   - Fix: Check connection strings, authentication

4. **Job Completion Error**:
   - Look for: "CRITICAL: Job completion check failed"
   - Likely cause: TaskManager issues, database access
   - Fix: Check TaskManager logic, database connectivity

### Phase 2: Test Individual Components
Use local testing to isolate:

```python
# Test 1: Service Factory
try:
    from services import ServiceFactory
    service = ServiceFactory.get_service('hello_world') 
    print("✅ ServiceFactory working")
except Exception as e:
    print(f"❌ ServiceFactory failed: {e}")

# Test 2: Task Repository  
try:
    from repositories import TaskRepository
    repo = TaskRepository()
    result = repo.update_task_status('test_id', 'processing')
    print(f"✅ TaskRepository working: {result}")
except Exception as e:
    print(f"❌ TaskRepository failed: {e}")

# Test 3: Task Manager
try:
    from task_manager import TaskManager  
    manager = TaskManager()
    print("✅ TaskManager import working")
except Exception as e:
    print(f"❌ TaskManager failed: {e}")
```

### Phase 3: Environment Validation
Check common Azure Functions issues:

1. **Environment Variables**:
   ```python
   import os
   required_vars = ['AzureWebJobsStorage', 'POSTGIS_HOST', 'POSTGIS_USER']
   for var in required_vars:
       if os.getenv(var):
           print(f"✅ {var} is set")
       else:
           print(f"❌ {var} missing")
   ```

2. **Import Paths**:
   ```python
   import sys
   print("Python path:", sys.path)
   
   try:
       import services, repositories, task_manager
       print("✅ Core modules importable")
   except ImportError as e:
       print(f"❌ Import failed: {e}")
   ```

## 🔍 Common Azure Functions Issues

### 1. Cold Start Problems
- **Symptom**: Intermittent failures, timeout errors
- **Solution**: Add function warming, increase timeout settings

### 2. Environment Variable Access
- **Symptom**: Configuration not found, authentication failures
- **Solution**: Check App Settings, connection string format

### 3. Import Path Issues
- **Symptom**: ModuleNotFoundError, import failures  
- **Solution**: Check file structure, __init__.py files, relative imports

### 4. Memory/Resource Limits
- **Symptom**: Out of memory, execution timeout
- **Solution**: Increase function memory allocation, optimize imports

### 5. Dependency Conflicts
- **Symptom**: Library version conflicts, runtime errors
- **Solution**: Check requirements.txt, Azure Functions runtime compatibility

## 📋 Systematic Testing Approach

### Step 1: Minimal Test
Create the simplest possible test job:
```python
minimal_payload = {
    'job_type': 'hello_world',
    'system': True
}
```

### Step 2: Monitor Execution
- Watch poison queue every 3 seconds
- Check Azure Functions logs immediately
- Look for enhanced logging ERROR messages

### Step 3: Isolate Variables
Test with different parameters:
- With/without dataset_id, resource_id, version_id
- Different message content
- Single vs multiple tasks (n=1 vs n=7)

### Step 4: Component Testing
Test each component independently:
- Service creation outside Azure Functions
- Repository access with same credentials
- Task data validation and serialization

## 🚀 Quick Fix Validation

Once error is identified and fixed:

1. **Deploy Fix**: `func azure functionapp publish rmhgeoapibeta --build remote`

2. **Clear Poison Queue**: 
   ```python
   requests.post('https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/monitor/poison')
   ```

3. **Test Simple Job**:
   ```python
   test_response = requests.post(
       'https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/hello_world',
       json={'job_type': 'hello_world', 'system': True}
   )
   ```

4. **Monitor for 30 seconds** - should see no poison messages

5. **Validate Job Completion**:
   ```python
   status_response = requests.get(f'https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/{job_id}')
   # Should show status='completed' and result_data populated
   ```

6. **Test 7-Hello**:
   ```python
   seven_hello_payload = {
       'job_type': 'hello_world',
       'dataset_id': 'test_7_hello',
       'resource_id': 'final_validation', 
       'version_id': 'v1',
       'n': 7,
       'message': 'Final 7-hello validation test',
       'system': True
   }
   ```

## 💡 Success Indicators

When fully fixed, expect:
- ✅ Zero poison messages for any hello_world job
- ✅ Jobs complete with `status='completed'`
- ✅ `result_data` contains hello statistics:
  ```json
  {
    "hello_statistics": {
      "total_hellos_requested": 7,
      "hellos_completed_successfully": 7, 
      "hellos_failed": 0,
      "success_rate": 100
    },
    "hello_messages": [
      "Hello from Job→Task architecture! (Hello #1)", 
      "Hello from Job→Task architecture! (Hello #2)",
      ...
    ]
  }
  ```
- ✅ Job→Task architecture fully operational for all multi-task operations

## 🔗 Related Documentation

- `CURRENT_INVESTIGATION_STATUS.md` - Current progress summary
- `function_app.py:1380-1458` - Enhanced error logging code
- `CONTROLLER_PATTERN.md` - Job→Task architecture documentation
- `API_REFERENCE.md` - Endpoint usage and testing

**Remember**: The core architecture is working perfectly. The issue is isolated to Azure Functions runtime environment execution.