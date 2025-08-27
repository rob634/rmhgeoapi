# Debug Parameter Logging Guide

This guide explains the comprehensive parameter logging system implemented to help identify and troubleshoot parameter mismatch issues in the controller pipeline.

## Overview

The system now includes thorough debug logging at multiple levels:

✅ **Function App Routing**: Parameter mapping from HTTP request to controller  
✅ **Controller Input**: Detailed parameter analysis with type validation  
✅ **Controller Validation**: Request validation logging with specific failures  
✅ **Task Creation**: Parameters being passed to task creation  
✅ **Parameter Type Checking**: Type mismatches and unusual parameter types

## Logging Levels

### 🔍 **DEBUG Level Logging**
Enable debug logging to see comprehensive parameter tracking:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Or for specific components
logger = logging.getLogger('base_controller')
logger.setLevel(logging.DEBUG)
```

### 📊 **Log Output Examples**

#### **1. Function App Routing**
```
🎯 Controller Routing - Operation: hello_world
  📊 Request Body Keys: ['dataset_id', 'resource_id', 'version_id', 'system', 'message']
  📋 Controller Request Keys: ['dataset_id', 'resource_id', 'version_id', 'operation_type', 'system', 'message']
  🎯 Controller Class: HelloWorldController
  🔍 Parameter Mapping: {
    'from_body': {'dataset_id': 'str', 'resource_id': 'str', 'message': 'str'},
    'to_controller': {'dataset_id': 'str', 'resource_id': 'str', 'operation_type': 'str', 'message': 'str'},
    'additional_params': ['message']
  }
```

#### **2. Controller Parameter Input**
```
🔍 [INPUT] HelloWorldController - Request Parameters:
  📋 Core Parameters:
    ✅ operation_type: hello_world
    ✅ dataset_id: test_dataset
    ✅ resource_id: test_resource
    ✅ version_id: v1
    ✅ system: True
  📎 Additional Parameters:
    📄 message (str): Test message for logging
  📊 Total parameters: 6
```

#### **3. Parameter Type Validation**
```
🔧 HelloWorldController - Validating parameter types...
  ✅ operation_type: str ✓
  ✅ dataset_id: str ✓
  ❌ resource_id: str ✓
  ⚠️ Type mismatch - system: expected bool, got str (true)
  📄 message: str
```

#### **4. Task Creation Context**
```
🔨 HelloWorldController - Task Creation Context:
  📋 Job ID: 1234abcd5678efgh...
  🎯 Controller: HelloWorldController
  📊 Task Creation Parameters:
    dataset_id: test_dataset
    resource_id: test_resource
    version_id: v1
    operation_type: hello_world
  🛠️ Custom Parameters (may affect task creation):
    message: Test message for logging
```

## Common Parameter Issues

### **❌ Issue 1: Missing Required Parameters**

**Log Output:**
```
🔍 [INPUT] HelloWorldController - Request Parameters:
  📋 Core Parameters:
    ✅ operation_type: hello_world
    ❌ dataset_id: None (MISSING)
    ❌ resource_id: None (MISSING)
    ✅ version_id: v1
    ✅ system: True
```

**Solution:**
- Check that all required parameters are included in request
- Verify parameter names are spelled correctly

### **❌ Issue 2: Parameter Type Mismatches**

**Log Output:**
```
⚠️ Type mismatch - dataset_id: expected str, got int (123)
⚠️ Type mismatch - system: expected bool, got str (true)
⚠️ Unusual type - custom_param: function (value: <function lambda at 0x...>)
```

**Solutions:**
- Convert parameters to expected types before sending
- Check JSON serialization - may convert booleans to strings
- Remove function or unusual type parameters

### **❌ Issue 3: Parameter Name Typos**

**Log Output:**
```
🔍 [INPUT] HelloWorldController - Request Parameters:
  📋 Core Parameters:
    ✅ operation_type: hello_world
    ✅ dataset_id: test
    ❌ resource_id: None (MISSING)  # <- Should be here
    ✅ version_id: v1
  📎 Additional Parameters:
    📄 resouce_id (str): test_resource  # <- Typo here
```

**Solution:**
- Fix parameter name spelling: `resouce_id` → `resource_id`

### **❌ Issue 4: Case Sensitivity Issues**

**Log Output:**
```
  📎 Additional Parameters:
    📄 Dataset_ID (str): test  # <- Wrong case
    📄 Operation_Type (str): hello_world  # <- Wrong case
```

**Solution:**
- Use exact case: `dataset_id`, `operation_type`, `resource_id`, etc.

## Troubleshooting Workflow

### **Step 1: Enable Debug Logging**
```python
# For local testing
import logging
logging.basicConfig(level=logging.DEBUG)

# For Azure Functions (in local.settings.json)
{
  "Values": {
    "AzureFunctionsJobHost__logging__logLevel__default": "Debug"
  }
}
```

### **Step 2: Send Test Request**
```bash
curl -X POST http://localhost:7071/api/jobs/hello_world \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "test",
    "resource_id": "test_resource",
    "version_id": "v1",
    "system": true
  }'
```

### **Step 3: Analyze Debug Output**

1. **Check Function App Routing**:
   - Verify request body keys match expected parameters
   - Check parameter mapping from body to controller

2. **Check Controller Input**:
   - Verify all core parameters are present and correct
   - Check parameter types match expectations
   - Review additional parameters for typos

3. **Check Validation**:
   - Look for controller-specific validation failures
   - Check validation log messages for specific issues

4. **Check Task Creation**:
   - Verify parameters reach task creation correctly
   - Check that custom parameters are preserved

### **Step 4: Fix Issues**
Based on the debug output:

- **Missing parameters**: Add to request body
- **Type mismatches**: Convert types or fix client serialization
- **Name typos**: Correct parameter names
- **Case issues**: Use correct case sensitivity
- **Unexpected parameters**: Remove or rename as needed

## Testing Debug Logging

Run the comprehensive test suite:
```bash
python test_debug_logging.py
```

This tests:
- Valid parameter scenarios
- Missing required parameters
- Wrong parameter types
- Parameter name typos
- Case sensitivity issues
- Complex nested parameters

## Integration with Development

### **Development Workflow**

1. **Always enable debug logging during development**
2. **Check parameter logging before investigating other issues**
3. **Use parameter logs to verify request structure**
4. **Add custom parameter logging for controller-specific needs**

### **Custom Parameter Logging**

Controllers can add their own parameter logging:

```python
class MyController(BaseJobController):
    def validate_request(self, request: Dict[str, Any]) -> bool:
        # Custom parameter logging for this controller
        self.logger.debug(f"🔧 MyController - Custom validation:")
        self.logger.debug(f"  Special param: {request.get('special_param')}")
        
        # Call parent validation
        return super().validate_request(request)
```

### **Production Considerations**

- **Debug logging is verbose** - use INFO or WARNING in production
- **Parameter values may contain sensitive data** - be cautious with logging
- **Log rotation** - ensure logs don't fill disk space
- **Performance** - debug logging has minimal performance impact but disable if not needed

## Best Practices

1. **Check debug logs first** when troubleshooting parameter issues
2. **Use structured parameter names** that are easy to identify in logs
3. **Validate parameter types early** in the request pipeline
4. **Document expected parameters** for each controller
5. **Test with debug logging enabled** during development
6. **Use parameter logging to verify API contract compliance**

This debug logging system provides comprehensive visibility into parameter flow through the controller pipeline, making it easy to identify and resolve parameter mismatch issues quickly.