# Master Implementation Plan

**Updated**: August 28, 2025  
**Status**: HelloWorldController proven working, others need validation  

## 📋 Document Contents Outline

Jump to specific sections with line numbers for quick navigation:

**Line 20**: 🎯 Simple Architecture Pattern (Job→Task Controller Pattern)  
**Line 47**: 🚨 IMMEDIATE PRIORITY - Sequential Job Chaining Framework Implementation  
**Line 143**: 🧪 HelloWorldSequential Test Implementation (Proves Job Chaining Works)  
**Line 245**: 📋 Controller Implementation Steps (Templates and Testing)  
**Line 348**: 🏗️ Vector Processing Plan (GeoPandas → PostGIS Pipeline)  
**Line 566**: 🗻 Raster Processing Plan (COG Conversion & Tiling)  
**Line 722**: 📊 Current Status Matrix (All Operations Overview)  
**Line 745**: 🎯 Success Criteria & Next Steps  

---

## 🎯 Simple Architecture Pattern

The proven Job→Task pattern is straightforward:

```
HTTP Request → Job Record + Job Queue Message
     ↓
Job Queue Trigger → Task Records + Task Queue Messages  
     ↓
Task Queue Triggers → Process Tasks → Update Task Records
     ↓
Last Task → Checks Job Completion → Updates Job Record
```

## ✅ Proven Working Implementation

**HelloWorldController** demonstrates the complete pattern:
- HTTP `/api/jobs/hello_world` creates job + queues job message
- Job queue trigger creates N task records + N task messages  
- Task queue triggers process each task independently
- Last completing task updates job to 'completed' with aggregated results
- **Result**: Perfect distributed completion without coordination servers

## 📋 Implementation Steps

### Step 1: Use HelloWorldController as Template ✅ COMPLETE

All new controllers should follow the exact pattern shown in `hello_world_controller.py`:

```python
class MyController(BaseJobController):
    def validate_operation_parameters(self, request: Dict[str, Any]) -> bool:
        # Validate request parameters
        
    def create_tasks(self, job_id: str, request: Dict[str, Any]) -> List[str]:
        # Create task records and return task IDs
        
    def aggregate_results(self, task_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        # Combine task results into job result
```

### Step 2: Implement Sequential Job Chaining Framework 🚨 IMMEDIATE PRIORITY

**CRITICAL**: Current architecture only supports parallel tasks. Vector processing requires sequential job chaining.

**DESIGN PHILOSOPHY**: Jobs = Sole Orchestration Layer
- Jobs manage sequential stages and workflow progression
- Tasks remain pure parallel execution units
- Clean separation: Jobs orchestrate, Tasks execute

#### Required Job Table Schema Enhancement

The job table requires 6 additional mandatory fields (already added to infrastructure_initializer.py):

```python
# Enhanced job record structure
job_record = {
    'job_id': 'abc123',                    # Existing: Unique job identifier
    'job_type': 'process_vector',          # Existing: Operation type
    'status': 'processing',                # Existing: Overall job status
    
    # NEW MANDATORY: Stage Management Attributes
    'stages': 3,                           # Total number of stages in job
    'current_stage_n': 2,                  # Current stage number (1-based)
    'current_stage': 'validate_file',      # Current stage name
    'stage_sequence': {                    # Stage number → stage name mapping
        1: 'open_file',
        2: 'validate_file', 
        3: 'batch_upload'
    },
    'stage_data': {                        # Inter-stage data passed between stages
        'file_info': {...},
        'validation_results': {...}
    },
    'stage_history': [                     # Completed stage history
        {
            'stage_n': 1,
            'stage': 'open_file',
            'completed_at': '2025-08-28T10:02:00Z',
            'duration_seconds': 120,
            'task_count': 1,
            'status': 'completed'
        }
    ]
}
```

#### Job Status Evolution Examples

**Single-stage job (no chaining)** - current HelloWorld pattern:
```python
{
    'stages': 1,
    'current_stage_n': 1,
    'current_stage': 'execute',
    'stage_sequence': {1: 'execute'},
    'status': 'processing' → 'completed'
}
```

**Multi-stage job (chaining)** - vector processing example:
```python
{
    'stages': 2,
    'current_stage_n': 1 → 2,
    'current_stage': 'preprocess' → 'upload',
    'stage_sequence': {1: 'preprocess', 2: 'upload'},
    'status': 'processing' → 'processing' → 'completed'
}
```

#### Required Implementation Components

1. **Enhanced TaskManager**: Add stage advancement logic
2. **Job Chaining Controller**: Base class for multi-stage jobs
3. **Stage Definition Framework**: Structured stage definitions
4. **Job Queue Re-entry**: Same job_id queued multiple times for different stages

#### Implementation Priority

**This blocks vector processing and tiled raster processing implementations.**

**Status**: Table schema updated ✅ | Implementation components needed ⚠️

---

## 🧪 HelloWorldSequential Test Implementation (Proves Job Chaining Works)

**Purpose**: Comprehensive test of sequential job chaining framework using proven HelloWorldController foundation.

**Date Designed**: August 28, 2025  
**Status**: Ready for implementation - detailed plan complete  
**Priority**: IMMEDIATE - Must implement before vector/raster processing  

### 🎯 3-Stage Test Architecture

**Job Flow Design**:
```
Stage 1: Initial Hello (n tasks)     →   Stage 2: Validation (1 task)     →   Stage 3: Response (n tasks)
├─ Task 1-1: "Hello from 1"         →    └─ Task 2-1: Validate all        →   ├─ Task 3-1: "Task 3-1 responding to Task 1-1"
├─ Task 1-2: "Hello from 2"         →      Stage 1 completions           →   ├─ Task 3-2: "Task 3-2 responding to Task 1-2"  
├─ Task 1-3: "Hello from 3"         →      (collects task_ids)           →   ├─ Task 3-3: "Task 3-3 responding to Task 1-3"
└─ ...                              →                                    →   └─ ...
```

**Key Validation Points**:
1. **Stage Progression**: Job advances through 3 distinct stages
2. **Inter-stage Data Flow**: Task IDs from Stage 1 → Stage 2 → Stage 3
3. **Task Count Consistency**: n tasks in Stage 1 = n tasks in Stage 3
4. **Job Completion**: Only completes after ALL 3 stages finish
5. **Result Aggregation**: Comprehensive statistics across all stages
6. **Actual Timing Metrics**: Real processing_time_seconds measurements

### 📋 Implementation Components Required

#### 1. HelloWorldSequentialController
```python
class HelloWorldSequentialController(BaseJobController):
    def get_supported_operations(self) -> List[str]:
        return ['hello_world_sequential']
    
    def validate_operation_parameters(self, request: Dict[str, Any]) -> bool:
        n = request.get('n', 1)
        if not isinstance(n, int) or not (1 <= n <= 20):  # Limited for testing
            raise InvalidRequestError("n must be integer between 1-20 for sequential test")
        return True
    
    def create_tasks(self, job_id: str, request: Dict[str, Any]) -> List[str]:
        # Initialize job with 3-stage configuration
        self._initialize_sequential_job(job_id, request)
        
        # Stage 1: Create initial hello tasks
        n = request.get('n', 1)
        base_message = request.get('message', 'Sequential Hello Test')
        
        task_ids = []
        for i in range(n):
            task_data = {
                'operation': 'hello_world_stage1',
                'hello_number': i + 1,
                'message': f"{base_message} - Initial Hello {i + 1}",
                'job_id': job_id,
                'stage': 1,
                'expected_total': n
            }
            task_id = self.task_manager.create_task(job_id, 'hello_world_stage1', task_data)
            task_ids.append(task_id)
        
        return task_ids
    
    def _initialize_sequential_job(self, job_id: str, request: Dict[str, Any]):
        """Initialize job with sequential stage configuration"""
        job_update = {
            'stages': 3,
            'current_stage_n': 1,
            'current_stage': 'initial_hello',
            'stage_sequence': {
                1: 'initial_hello',
                2: 'validation', 
                3: 'response'
            },
            'stage_data': {},
            'stage_history': []
        }
        self.job_repository.update_job_stages(job_id, job_update)
```

#### 2. Enhanced TaskManager - Stage Advancement Logic
```python
# Add to task_manager.py
def check_stage_completion_and_advance(self, job_id: str, completed_task_id: str):
    """Check if current stage is complete and advance to next stage if ready"""
    
    # Get current job state
    job = self.job_repository.get_job(job_id)
    if not job:
        return
    
    current_stage = job.get('current_stage_n', 1)
    total_stages = job.get('stages', 1)
    
    # Get all tasks for current stage
    stage_tasks = self._get_stage_tasks(job_id, current_stage)
    completed_tasks = [t for t in stage_tasks if t.get('status') == 'completed']
    
    # Check if current stage is complete
    if len(completed_tasks) == len(stage_tasks):
        logger.info(f"🎯 Stage {current_stage} completed for job {job_id}")
        
        # Update stage history with actual timing
        self._record_stage_completion(job_id, current_stage, completed_tasks)
        
        if current_stage < total_stages:
            # Advance to next stage
            self._advance_to_next_stage(job_id, completed_tasks)
        else:
            # Job completely finished
            self._complete_sequential_job(job_id, completed_tasks)

def _record_stage_completion(self, job_id: str, stage_n: int, completed_tasks: List[Dict]):
    """Record actual stage completion with real timing metrics"""
    # Calculate real stage duration from first task start to last task completion
    task_times = [t.get('completed_at') for t in completed_tasks if t.get('completed_at')]
    if task_times:
        stage_start = min(datetime.fromisoformat(t) for t in task_times)
        stage_end = max(datetime.fromisoformat(t) for t in task_times)
        actual_duration = (stage_end - stage_start).total_seconds()
    else:
        actual_duration = 0.0
    
    stage_record = {
        'stage_n': stage_n,
        'stage': self._get_stage_name(stage_n),
        'completed_at': datetime.now(timezone.utc).isoformat(),
        'duration_seconds': actual_duration,  # REAL measurement
        'task_count': len(completed_tasks),
        'status': 'completed'
    }
    
    # Add to job's stage_history
    job = self.job_repository.get_job(job_id)
    stage_history = json.loads(job.get('stage_history', '[]'))
    stage_history.append(stage_record)
    
    self.job_repository.update_job_field(job_id, 'stage_history', json.dumps(stage_history))
```

#### 3. Task Router - 3 New Task Handlers
```python
# Add to task_router.py

def _handle_hello_world_stage1(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
    """Stage 1: Generate hello message with actual timing"""
    start_time = time.time()
    
    hello_number = task_data['hello_number']
    message = task_data['message']
    time.sleep(0.001)  # Simulate minimal processing
    
    processing_time = time.time() - start_time
    
    return {
        'status': 'success',
        'hello_number': hello_number,
        'message': f"Task {task_data.get('task_id', 'unknown')} says: {message}",
        'stage': 1,
        'task_id': task_data.get('task_id'),
        'processing_time_seconds': processing_time
    }

def _handle_hello_world_stage2_validation(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
    """Stage 2: Validate Stage 1 completion and prepare Stage 3 task mapping"""
    start_time = time.time()
    
    job_id = task_data['job_id']
    
    # Get all Stage 1 task results from job's stage_data
    job = self.job_repository.get_job(job_id)
    stage_data = json.loads(job.get('stage_data', '{}'))
    stage1_results = stage_data.get('stage1_results', [])
    
    # Validate all Stage 1 tasks completed successfully
    successful_tasks = [r for r in stage1_results if r.get('status') == 'success']
    failed_tasks = [r for r in stage1_results if r.get('status') != 'success']
    
    # Prepare task mapping for Stage 3
    task_mapping = {}
    for i, result in enumerate(successful_tasks):
        stage1_task_id = result.get('task_id')
        stage3_task_number = i + 1
        task_mapping[stage3_task_number] = {
            'responds_to_task_id': stage1_task_id,
            'original_hello_number': result.get('hello_number'),
            'original_message': result.get('message')
        }
    
    processing_time = time.time() - start_time
    
    return {
        'status': 'success',
        'stage': 2,
        'validation_summary': {
            'stage1_tasks_total': len(stage1_results),
            'stage1_tasks_successful': len(successful_tasks),
            'stage1_tasks_failed': len(failed_tasks),
            'ready_for_stage3': len(successful_tasks) > 0
        },
        'stage3_task_mapping': task_mapping,
        'processing_time_seconds': processing_time
    }

def _handle_hello_world_stage3_response(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
    """Stage 3: Generate response messages referencing Stage 1 tasks"""
    start_time = time.time()
    
    current_task_id = task_data.get('task_id')
    responds_to_task_id = task_data['responds_to_task_id']
    original_hello_number = task_data['original_hello_number']
    response_number = task_data['response_number']
    
    time.sleep(0.001)  # Simulate minimal processing
    
    # Generate the specific response message format
    response_message = f"Task {current_task_id} saying hello to {responds_to_task_id}"
    
    processing_time = time.time() - start_time
    
    return {
        'status': 'success',
        'stage': 3,
        'response_number': response_number,
        'current_task_id': current_task_id,
        'responds_to_task_id': responds_to_task_id,
        'response_message': response_message,
        'original_hello_number': original_hello_number,
        'conversation': {
            'stage1_said': task_data['original_message'],
            'stage3_responds': response_message
        },
        'processing_time_seconds': processing_time
    }
```

### 🧪 Expected Test Results

#### Test Request:
```bash
curl -X POST /api/jobs/hello_world_sequential \
  -d '{
    "dataset_id": "sequential_test", 
    "resource_id": "3_stage_hello",
    "version_id": "v1",
    "n": 3,
    "message": "Sequential Test"
  }'
```

#### Expected Final Job Result:
```json
{
  "job_id": "abc123...",
  "status": "completed",
  "stages": 3,
  "current_stage": "response",
  "result_data": {
    "sequential_hello_statistics": {
      "total_stages_completed": 3,
      "stage1_hellos_requested": 3,
      "stage1_hellos_successful": 3,
      "stage2_validation_passed": true,
      "stage3_responses_generated": 3,
      "overall_success_rate": "100%"
    },
    "stage_conversations": [
      {
        "stage1_task_id": "task_1_abc",
        "stage1_message": "Task task_1_abc says: Sequential Test - Initial Hello 1",
        "stage3_task_id": "task_3_def", 
        "stage3_response": "Task task_3_def saying hello to task_1_abc"
      }
    ],
    "stage_history": [
      {
        "stage_n": 1,
        "stage": "initial_hello",
        "task_count": 3,
        "status": "completed",
        "duration_seconds": 0.003
      },
      {
        "stage_n": 2, 
        "stage": "validation",
        "task_count": 1,
        "status": "completed",
        "duration_seconds": 0.001
      },
      {
        "stage_n": 3,
        "stage": "response",
        "task_count": 3, 
        "status": "completed",
        "duration_seconds": 0.003
      }
    ]
  }
}
```

### 🎯 Success Criteria

✅ **Stage Progression**: Job moves through stages 1→2→3  
✅ **Task ID Flow**: Stage 1 task_ids appear in Stage 3 responses  
✅ **Count Consistency**: n Stage 1 tasks = n Stage 3 tasks  
✅ **Inter-stage Data**: Stage 2 validation passes data to Stage 3  
✅ **Job Completion**: Only completes after ALL stages finish  
✅ **Response Format**: Exact message format: "Task {current} saying hello to {stage1}"  
✅ **Real Timing**: Actual processing_time_seconds measurements  

### 📁 Files to Create/Modify

1. **`hello_world_sequential_controller.py`** - New sequential controller
2. **Enhanced `task_manager.py`** - Stage advancement logic  
3. **Enhanced `task_router.py`** - 3 new task handlers
4. **Enhanced `controller_factory.py`** - Route `hello_world_sequential`
5. **Enhanced `repositories.py`** - Stage data management
6. **Test file**: `test_hello_world_sequential.py`

### 🚀 Implementation Priority

**CRITICAL**: This HelloWorldSequential test will **definitively prove the sequential job chaining framework works** before implementing vector/raster processing. It builds on proven HelloWorldController foundation while validating complete sequential workflow.

**Next Claude**: Start with `hello_world_sequential_controller.py` - the detailed implementation above is complete and ready to code!

---

### Step 3: Test Existing Operations ⚠️ AFTER SEQUENTIAL FRAMEWORK

**Testing Required After Sequential Framework**:
1. **list_container** - Test if using controller pattern
2. **sync_container** - Test if using controller pattern (STAC operations)

**Testing Steps**:
```bash
# Test list_container
curl -X POST /api/jobs/list_container -d '{"dataset_id":"test","system":true}'

# Test sync_container  
curl -X POST /api/jobs/sync_container -d '{"dataset_id":"rmhazuregeobronze","resource_id":"all","version_id":"v1"}'

# Check if they follow the pattern:
# 1. Job record created in jobs table?
# 2. Tasks created in tasks table? 
# 3. Job completes with aggregated results?
```

### Step 3: Validate All Other Operations ⏳ PENDING

**Operations Status Unknown** (need validation):
- catalog_file (STAC operations)
- cog_conversion (Raster operations)  
- database_health (Database operations)
- get_database_summary (Metadata operations)
- generate_tiling_plan (Tiling operations)
- All other operation types

**For Each Operation**:
1. Test HTTP endpoint
2. Verify job→task creation pattern
3. Check task completion and job aggregation
4. Fix if using deprecated service pattern

## 🛠️ Controller Creation Process

When creating a new controller:

### 1. Copy HelloWorldController Pattern
```python
# Use hello_world_controller.py as exact template
# Change only the operation-specific logic
# Keep all the job→task lifecycle code identical
```

### 2. Register in ControllerFactory
```python
# In controller_factory.py:
elif operation_type in ['my_operation']:
    from my_controller import MyController
    controller = MyController()
```

### 3. Add Task Handler 
```python
# In task_router.py:
def _handle_my_operation(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
    # Process individual task
    # Return result dictionary
```

### 4. Test End-to-End
- HTTP request creates job
- Job queue creates tasks  
- Tasks process and complete
- Job shows 'completed' with results

## 📊 Current Status

| Operation Type | Controller Status | Pattern Verified | Next Action |
|----------------|------------------|------------------|-------------|
| hello_world | ✅ Working | ✅ Yes | Template for others |
| list_container | ❓ Unknown | ❓ Needs Testing | **Test immediately** |
| sync_container | ❓ Unknown | ❓ Needs Testing | **Test immediately** |
| catalog_file | ❓ Unknown | ❓ Needs Testing | Test after containers |
| cog_conversion | ❓ Unknown | ❓ Needs Testing | Test after STAC |
| database_health | ❓ Unknown | ❓ Needs Testing | Test after raster |
| All others | ❓ Unknown | ❓ Needs Testing | Test systematically |

## 🎯 Success Criteria

For each operation to be considered "working":

1. **HTTP Request** → Creates job record in jobs table ✅
2. **Job Queue Trigger** → Creates task records in tasks table ✅
3. **Task Queue Triggers** → Process tasks, update task status ✅  
4. **Task Completion** → Last task aggregates results into job ✅
5. **Job Result** → Shows 'completed' with comprehensive data ✅

**If any step fails** → Operation needs controller pattern implementation

## 🚨 What NOT to Do

❌ **Don't create complex phases** - HelloWorld pattern works, just copy it  
❌ **Don't add "enforcement"** - Pattern already enforced by working implementation  
❌ **Don't migrate old code** - Test what exists, fix what's broken  
❌ **Don't create subdirectories** - All files in root for Azure Functions  
❌ **Don't overcomplicate** - The working pattern is simple and elegant  

## ⏭️ Immediate Next Steps

1. **🚨 CRITICAL: Implement Sequential Task Chaining Framework** 
   - Task dependency tracking system
   - Job stage management with sequential status updates
   - TaskManager enhancement for sequential + parallel patterns
   - Task chaining capability (task1 → queue task2)
2. **Test list_container operation** (after sequential framework)
3. **Test sync_container operation** (after sequential framework)  
4. **Implement vector processing** (requires sequential framework)
5. **Implement tiled raster processing** (requires sequential framework)

## 📝 Notes

- **HelloWorldController proves the architecture works perfectly**
- **No complex migration needed** - just test and fix operations one by one
- **Pattern is production-ready** - distributed completion works flawlessly  
- **Focus on testing** - find what's broken, fix using working template
- **Keep it simple** - don't over-engineer what already works

The Job→Task pattern is **complete and proven**. We just need to validate which operations are using it correctly and fix the ones that aren't.

---

## 🏗️ Vector Processing Plan

**Status**: Architecture design based on ancient code - needs VectorController implementation  

### ⚠️ STATUS WARNING
**IMPORTANT**: This plan assumes VectorController uses the clean Job→Task architecture, but this has NOT been validated. Only HelloWorldController has been proven to work with the controller pattern.

**Before implementing**: Validate that VectorController follows the Job→Task pattern shown in JOB_TASK_ARCHITECTURE_GUIDE.md.

### 🎯 Global Settings

```python
# Global vector processing configuration
MAX_FEATURES_PER_CHUNK = 10000  # Features per PostGIS upload task
SUPPORTED_FORMATS = [
    'shp',      # Zipped shapefile
    'csv',      # CSV with lat/lon or WKT
    'gpkg',     # GeoPackage (single layer)
    'kml',      # KML
    'kmz',      # KMZ
    'geojson'   # GeoJSON
]
FUNCTION_TIMEOUT_MINUTES = 5  # Chunk size must complete before this
```

### 📋 Processing Workflow

#### Sequential Preprocessing (Steps 1-4)
**Single orchestrator task** that prepares "PostGIS Ready" data:

1. **Load File** → GeoPandas GeoDataFrame (validates format support)
2. **Remove Z/M Values** → Clean 2D geometries only  
3. **Ensure Single Geometry Type** → Promote mixed types (Point+MultiPoint→MultiPoint) or fail
4. **Reproject to EPSG:4326** → PostGIS ready data

#### Parallel Upload (Step 5)  
**N upload tasks** based on feature count and chunk size

### 🏗️ Architecture Implementation

#### VectorController (Single Job, Orchestrator Pattern)

```python
class VectorController(BaseJobController):
    """Handles complete vector processing pipeline"""
    
    def get_supported_operations(self) -> List[str]:
        return ['process_vector']
    
    def validate_operation_parameters(self, request: Dict[str, Any]) -> bool:
        # Validate file exists and format is supported
        resource_id = request.get('resource_id')
        if not resource_id:
            raise InvalidRequestError("resource_id is required")
        
        file_extension = resource_id.split('.')[-1].lower()
        if file_extension not in SUPPORTED_FORMATS:
            raise InvalidRequestError(f"Unsupported format: {file_extension}")
        
        # Validate target table name if provided
        target_table = request.get('target_table')
        if target_table and not target_table.replace('_', '').isalnum():
            raise InvalidRequestError("target_table must be alphanumeric")
        
        return True
    
    def create_tasks(self, job_id: str, request: Dict[str, Any]) -> List[str]:
        # Single orchestrator task that handles preprocessing + spawns upload tasks
        orchestrator_data = {
            'operation': 'vector_orchestrator',
            'dataset_id': request['dataset_id'],
            'resource_id': request['resource_id'],
            'target_table': request.get('target_table'),
            'target_schema': request.get('target_schema', 'geo'),
            'load_method': request.get('load_method', 'replace'),  # replace, append
            'max_features_per_chunk': MAX_FEATURES_PER_CHUNK
        }
        
        task_id = self.create_task(job_id, orchestrator_data)
        return [task_id]
    
    def aggregate_results(self, task_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        # Orchestrator + N upload task results
        if not task_results:
            return {'status': 'error', 'error': 'No results'}
        
        # First result is orchestrator
        orchestrator_result = task_results[0]
        upload_results = task_results[1:] if len(task_results) > 1 else []
        
        if orchestrator_result.get('status') != 'success':
            return orchestrator_result  # Return preprocessing error
        
        # Aggregate upload results
        total_features = sum(r.get('features_uploaded', 0) for r in upload_results)
        failed_chunks = [r for r in upload_results if r.get('status') != 'success']
        
        return {
            'status': 'success' if not failed_chunks else 'partial_success',
            'table': f"{orchestrator_result.get('target_schema')}.{orchestrator_result.get('target_table')}",
            'total_features_loaded': total_features,
            'upload_chunks': len(upload_results),
            'failed_chunks': len(failed_chunks),
            'preprocessing_stats': orchestrator_result.get('preprocessing_stats', {}),
            'processing_time_seconds': sum(r.get('processing_time_seconds', 0) for r in task_results),
            'geometry_type': orchestrator_result.get('final_geometry_type'),
            'original_crs': orchestrator_result.get('original_crs'),
            'features_per_chunk': MAX_FEATURES_PER_CHUNK
        }
```

#### Task Handlers

```python
# In task_router.py

def _handle_vector_orchestrator(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sequential preprocessing (steps 1-4) + spawn parallel upload tasks (step 5)
    """
    from vector_processor import VectorProcessor
    processor = VectorProcessor()
    
    try:
        # Steps 1-4: Sequential preprocessing
        preprocessing_result = processor.preprocess_vector(
            dataset_id=task_data['dataset_id'],
            resource_id=task_data['resource_id']
        )
        
        if preprocessing_result['status'] != 'success':
            return preprocessing_result
        
        # Get preprocessed data info
        gdf_info = preprocessing_result['geodataframe_info']
        total_features = gdf_info['feature_count']
        chunk_size = task_data['max_features_per_chunk']
        
        # Calculate number of upload chunks needed
        chunk_count = (total_features + chunk_size - 1) // chunk_size  # Ceiling division
        
        # Generate target table name if not provided
        target_table = task_data['target_table'] or self._generate_table_name(task_data['resource_id'])
        
        # Step 5: Create parallel upload tasks
        from task_manager import TaskManager
        task_manager = TaskManager()
        
        upload_tasks = []
        for chunk_idx in range(chunk_count):
            start_idx = chunk_idx * chunk_size
            end_idx = min(start_idx + chunk_size, total_features)
            
            upload_task_data = {
                'operation': 'upload_vector_chunk',
                'preprocessed_data_blob': preprocessing_result['processed_data_blob'],
                'start_feature': start_idx,
                'end_feature': end_idx,
                'target_table': target_table,
                'target_schema': task_data['target_schema'],
                'load_method': task_data['load_method'],
                'create_table': chunk_idx == 0,  # First chunk creates table
                'parent_job_id': task_data['parent_job_id'],
                'chunk_index': chunk_idx
            }
            
            upload_task_id = task_manager.create_task(
                task_data['parent_job_id'],
                'upload_vector_chunk', 
                upload_task_data
            )
            upload_tasks.append(upload_task_id)
        
        return {
            'status': 'success',
            'target_table': target_table,
            'target_schema': task_data['target_schema'],
            'upload_tasks_created': len(upload_tasks),
            'total_features': total_features,
            'chunk_size': chunk_size,
            'preprocessing_stats': {
                'original_feature_count': gdf_info['original_feature_count'],
                'final_feature_count': total_features,
                'original_crs': gdf_info['original_crs'],
                'final_crs': 'EPSG:4326',
                'geometry_type_changes': gdf_info['geometry_type_changes'],
                'z_m_values_removed': gdf_info['z_m_removed']
            },
            'final_geometry_type': gdf_info['final_geometry_type'],
            'original_crs': gdf_info['original_crs']
        }
        
    except Exception as e:
        return {
            'status': 'error',
            'error': str(e),
            'message': 'Vector preprocessing failed'
        }

def _handle_upload_vector_chunk(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
    """Upload single chunk of preprocessed vector data to PostGIS"""
    from vector_uploader import VectorUploader
    uploader = VectorUploader()
    
    try:
        result = uploader.upload_chunk(
            preprocessed_data_blob=task_data['preprocessed_data_blob'],
            start_feature=task_data['start_feature'],
            end_feature=task_data['end_feature'],
            target_table=task_data['target_table'],
            target_schema=task_data['target_schema'],
            load_method=task_data['load_method'],
            create_table=task_data['create_table']
        )
        
        return {
            'status': 'success',
            'chunk_index': task_data['chunk_index'],
            'features_uploaded': result['features_uploaded'],
            'table': f"{task_data['target_schema']}.{task_data['target_table']}",
            'processing_time_seconds': result['processing_time'],
            'chunk_range': f"{task_data['start_feature']}-{task_data['end_feature']}"
        }
        
    except Exception as e:
        return {
            'status': 'error',
            'chunk_index': task_data['chunk_index'],
            'error': str(e),
            'chunk_range': f"{task_data['start_feature']}-{task_data['end_feature']}"
        }
```

### 🧪 Vector Testing Plan

#### Test Case 1: Small GeoJSON (1k features)
```bash
curl -X POST /api/jobs/process_vector \
  -d '{
    "dataset_id": "rmhazuregeobronze",
    "resource_id": "small_data.geojson", 
    "target_table": "test_small",
    "version_id": "v1"
  }'

# Expected: 1 orchestrator + 1 upload task, ~30 seconds, 1k features in geo.test_small
```

#### Test Case 2: Large Shapefile (100k features)  
```bash
curl -X POST /api/jobs/process_vector \
  -d '{
    "dataset_id": "rmhazuregeobronze",
    "resource_id": "counties_usa.zip",
    "target_table": "us_counties", 
    "version_id": "v1"
  }'

# Expected: 1 orchestrator + 10 upload tasks, ~5 minutes, 100k features in geo.us_counties
```

---

## 🗻 Raster Processing Plan

**Status**: Architecture design - needs RasterController implementation  

### ⚠️ STATUS WARNING
**IMPORTANT**: This plan assumes RasterController uses the clean Job→Task architecture, but this has NOT been validated. Only HelloWorldController has been proven to work with the controller pattern.

**Before implementing**: Validate that RasterController follows the Job→Task pattern shown in JOB_TASK_ARCHITECTURE_GUIDE.md.

### 🎯 Global Settings

```python
# Global raster processing configuration
MAX_RASTER_SIZE_GB = 2.0  # Files larger than this get tiled
TARGET_TILE_SIZE_GB = 1.0  # Target size for tiles
```

### 📋 Use Cases

#### Use Case 1: Standard Raster Processing (≤2GB)
**Trigger**: Single raster file ≤ 2GB  
**Pattern**: 1 job → 1 task → 1 COG output  

**Controller**: `RasterController`
```python
def create_tasks(self, job_id: str, request: Dict[str, Any]) -> List[str]:
    # Single task for complete raster processing pipeline
    task_data = {
        'operation': 'process_raster_complete',
        'dataset_id': request['dataset_id'],
        'resource_id': request['resource_id'],
        'processing_steps': [
            'validate',      # Validate raster integrity
            'reproject',     # Reproject to EPSG:4326 if needed
            'optimize',      # Bit-depth optimization
            'create_cog',    # Convert to Cloud Optimized GeoTIFF
            'validate_cog',  # Validate COG structure
            'catalog_stac'   # Create/update STAC entry
        ]
    }
    
    task_id = self.create_task(job_id, task_data)
    return [task_id]
```

**Task Handler**: `_handle_process_raster_complete`
- Input: Raw raster file from Bronze container
- Processing: Validation → Reprojection → Optimization → COG conversion → Validation
- Output: Single COG in Silver container + STAC entry

**Expected Duration**: 5-30 seconds for small files, up to 5 minutes for 2GB files

#### Use Case 2: Large Raster Tiling (>2GB)
**Trigger**: Single raster file > 2GB  
**Pattern**: 1 job → 1 orchestrator task → N tile tasks → N COG outputs  

**Controller**: `TiledRasterController`
```python
def create_tasks(self, job_id: str, request: Dict[str, Any]) -> List[str]:
    # Single orchestrator task that will create tile tasks
    orchestrator_data = {
        'operation': 'tiling_orchestrator',
        'dataset_id': request['dataset_id'],
        'resource_id': request['resource_id'],
        'target_tile_size_gb': TARGET_TILE_SIZE_GB,
        'max_raster_size_gb': MAX_RASTER_SIZE_GB
    }
    
    task_id = self.create_task(job_id, orchestrator_data)
    return [task_id]
```

**Step 1 - Orchestrator Task**: `_handle_tiling_orchestrator`
1. Analyze source raster dimensions and size
2. Calculate optimal tile grid using PostGIS
3. Create tile records in `geo.tiles` table
4. Queue N `process_tile` tasks (one per tile)

**Step 2 - Tile Tasks**: `_handle_process_tile` (N parallel tasks)
- Input: Tile bounds + source raster reference
- Processing: Extract tile → Validate → Reproject → COG conversion → Validate
- Output: Individual COG per tile in Silver container

**Step 3 - Collection Task**: `_handle_create_tiled_collection`
- Input: All completed tile COGs
- Processing: Create STAC collection linking all tiles as single dataset
- Output: STAC collection + optional VRT/JSON mosaic for easy access

**Expected Result**: 
- 31.8GB raster → ~32 tiles of 1GB each → ~32 COGs + 1 collection entry
- Total processing time: 10-20 minutes (parallel tile processing)

### 🏗️ Raster Architecture Implementation

#### Required Controllers

```python
class RasterController(BaseJobController):
    """Handles single raster processing (≤2GB)"""
    
    def get_supported_operations(self) -> List[str]:
        return ['process_raster']
    
    def validate_operation_parameters(self, request: Dict[str, Any]) -> bool:
        # Validate file exists and is ≤2GB
        pass
    
    def create_tasks(self, job_id: str, request: Dict[str, Any]) -> List[str]:
        # Single complete processing task
        pass
    
    def aggregate_results(self, task_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        # Single task result with COG details + STAC ID
        pass

class TiledRasterController(BaseJobController):
    """Handles large raster tiling (>2GB)"""
    
    def get_supported_operations(self) -> List[str]:
        return ['process_large_raster', 'tile_raster']
    
    def validate_operation_parameters(self, request: Dict[str, Any]) -> bool:
        # Validate file exists and is >2GB
        pass
    
    def create_tasks(self, job_id: str, request: Dict[str, Any]) -> List[str]:
        # Single orchestrator task (creates tile tasks dynamically)
        pass
    
    def aggregate_results(self, task_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        # Orchestrator + N tile results + collection summary
        pass
```

#### Required Task Handlers

```python
# In task_router.py

def _handle_process_raster_complete(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
    """Complete raster processing pipeline for single file"""
    from raster_processor import RasterProcessor
    processor = RasterProcessor()
    
    result = processor.process_complete_pipeline(
        dataset_id=task_data['dataset_id'],
        resource_id=task_data['resource_id'],
        steps=task_data['processing_steps']
    )
    
    return {
        'status': 'success',
        'cog_path': result['cog_path'],
        'stac_id': result['stac_id'],
        'processing_stats': result['stats']
    }

def _handle_tiling_orchestrator(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
    """Create tiling plan and spawn tile processing tasks"""
    from tiling_service import TilingService
    tiler = TilingService()
    
    # Create tiling plan in PostGIS
    tiling_plan = tiler.create_tiling_plan(
        dataset_id=task_data['dataset_id'],
        resource_id=task_data['resource_id'],
        target_tile_size_gb=task_data['target_tile_size_gb']
    )
    
    # Queue tile processing tasks
    from task_manager import TaskManager
    task_manager = TaskManager()
    
    tile_tasks = []
    for tile_id, tile_bounds in tiling_plan['tiles'].items():
        tile_task_data = {
            'operation': 'process_tile',
            'tile_id': tile_id,
            'bounds': tile_bounds,
            'source_dataset': task_data['dataset_id'],
            'source_resource': task_data['resource_id'],
            'parent_job_id': task_data['parent_job_id']
        }
        
        tile_task_id = task_manager.create_task(
            task_data['parent_job_id'],
            'process_tile',
            tile_task_data
        )
        tile_tasks.append(tile_task_id)
    
    return {
        'status': 'success',
        'tiling_plan_id': tiling_plan['plan_id'],
        'tiles_created': len(tile_tasks),
        'tile_task_ids': tile_tasks
    }

def _handle_process_tile(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
    """Process individual tile from large raster"""
    from tile_processor import TileProcessor
    processor = TileProcessor()
    
    result = processor.process_tile(
        tile_id=task_data['tile_id'],
        bounds=task_data['bounds'],
        source_dataset=task_data['source_dataset'],
        source_resource=task_data['source_resource']
    )
    
    return {
        'status': 'success',
        'tile_id': task_data['tile_id'],
        'cog_path': result['cog_path'],
        'tile_size_gb': result['size_gb'],
        'processing_time_seconds': result['duration']
    }
```

### 🧪 Raster Testing Plan

#### Test Case 1: Standard Raster (500MB)
```bash
curl -X POST /api/jobs/process_raster \
  -d '{"dataset_id":"rmhazuregeobronze","resource_id":"small_raster.tif","version_id":"v1"}'

# Expected: Single task, ~30 seconds, 1 COG output
```

#### Test Case 2: Large Raster (31.8GB)
```bash
curl -X POST /api/jobs/tile_raster \
  -d '{"dataset_id":"rmhazuregeobronze","resource_id":"sau08feb2019ps.tif","version_id":"v1"}'

# Expected: 1 orchestrator + ~32 tile tasks, ~15 minutes, 32 COGs + collection
```

---

## 📊 Current Status Matrix