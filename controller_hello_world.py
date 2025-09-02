# ============================================================================
# CLAUDE CONTEXT - CONFIGURATION
# ============================================================================
# PURPOSE: HelloWorld workflow controller demonstrating Job→Stage→Task orchestration
# SOURCE: Inherited from BaseController (Environment + Managed Identity)
# SCOPE: Job-specific HelloWorld workflow with two-stage demonstration pattern
# VALIDATION: Workflow schema validation + HelloWorld parameter validation
# ============================================================================

"""
HelloWorld Controller - Job→Stage→Task Architecture Reference Implementation

Concrete controller implementation demonstrating the complete Job→Stage→Task
orchestration pattern for Azure Geospatial ETL Pipeline. Provides a two-stage
"Hello Worlds → Worlds Reply" workflow that validates all architectural components
and serves as the reference implementation for other controllers.

Architecture Demonstration:
    JOB: HelloWorld (Controller orchestrates entire workflow)
     ├── STAGE 1: Greeting Stage (Sequential coordination)
     │   ├── HelloWorldGreetingTask (Service layer - Parallel)
     │   ├── HelloWorldGreetingTask (Service layer - Parallel)
     │   └── HelloWorldGreetingTask (Service layer - Parallel)
     │                     ↓ Last task completes stage
     ├── STAGE 2: Reply Stage (Sequential coordination)
     │   ├── HelloWorldReplyTask (Service layer - Parallel)
     │   ├── HelloWorldReplyTask (Service layer - Parallel)
     │   └── HelloWorldReplyTask (Service layer - Parallel)
     │                     ↓ Last task completes stage
     └── COMPLETION: Aggregate results with comprehensive statistics

Key Features:
- Two-stage sequential workflow with parallel task execution
- Dynamic task creation based on 'n' parameter (fan-out pattern)
- Pydantic workflow definition validation and parameter schemas
- Inter-stage result passing from Greeting to Reply stage
- Comprehensive result aggregation with statistics and metadata
- "Last task turns out the lights" distributed completion detection
- Idempotent job processing with SHA256-based job IDs

Workflow Validation:
- Stage orchestration and sequential execution patterns
- Parallel task creation and execution within stages
- Task result collection and inter-stage data flow
- Job completion detection across distributed tasks
- Error handling and partial failure scenarios
- Result formatting for API consumption

Controller Responsibilities (Orchestration Layer):
- Define job_type and workflow stages (no business logic)
- Validate job parameters against Pydantic schemas
- Create task definitions for parallel execution
- Coordinate stage transitions and data passing
- Aggregate final results from all completed tasks
- Handle job completion and status management

Business Logic Separation:
- Controller: Stage coordination and task creation (THIS MODULE)
- Service: Task business logic execution (service_hello_world.py)
- Repository: Data persistence and retrieval (repository_data.py)

Integration Points:
- Used by trigger_submit_job.py for job creation
- Creates TaskDefinition objects for queue processing
- Interfaces with RepositoryFactory for job/task persistence
- Calls service_hello_world.py tasks for business logic
- Provides results to trigger_get_job_status.py

Parameter Schema:
- n: Number of parallel tasks per stage (default: 1, validates 1-10)
- message: Base message content for greeting generation
- dataset_id, resource_id, version_id: Standard DDH parameters
- system: Boolean flag for bypassing validation

Usage Examples:
    # Job creation (typically via HTTP API)
    controller = HelloWorldController()
    job_id = controller.generate_job_id(parameters)
    job_record = controller.create_job_record(job_id, parameters)
    
    # Stage processing (typically via queue processing)
    result = controller.process_job_stage(job_record, stage=1, ...)

Author: Azure Geospatial ETL Team
"""

from typing import List, Dict, Any
from datetime import datetime

from util_logger import LoggerFactory, ComponentType
from controller_base import BaseController
from model_core import (
    TaskDefinition, JobExecutionContext, 
    StageExecutionContext, TaskStatus
)


class HelloWorldController(BaseController):
    """
    Test controller implementing Hello World → Worlds Reply pattern.
    
    Two-Stage Workflow:
    1. Hello Worlds Stage: Creates n parallel tasks saying "Hello from task_{i}!"
    2. Worlds Reply Stage: Creates n parallel tasks responding to stage 1 results
    
    This pattern validates:
    - Stage orchestration and sequential execution
    - Parallel task creation and execution within stages  
    - Inter-stage data passing
    - Comprehensive result aggregation
    - "Last task turns out the lights" completion detection
    """
    
    def __init__(self):
        super().__init__()
        self.logger = LoggerFactory.get_logger(ComponentType.CONTROLLER, "HelloWorldController")
        self.logger.info(f"HelloWorldController initialized with {len(self.workflow_definition.stages)} stages")
    
    def get_job_type(self) -> str:
        """Return the job type identifier"""
        return "hello_world"
    
    
    
    def create_stage_tasks(self, context: StageExecutionContext) -> List[TaskDefinition]:
        """
        Create tasks for the specified stage.
        
        Stage 1: Create n greeting tasks
        Stage 2: Create n reply tasks using stage 1 results
        """
        n = context.job_parameters.get('n', 1)
        message = context.job_parameters.get('message', 'Hello World')
        
        tasks = []
        
        if context.stage_number == 1:
            # Stage 1: Hello Worlds - Create greeting tasks
            self.logger.info(f"Creating {n} greeting tasks for Stage 1")
            
            for i in range(n):
                task_id = f"{context.job_id}_stage1_task{i+1}"
                task_def = TaskDefinition(
                    task_id=task_id,
                    task_type="hello_world_greeting",
                    stage_number=1,
                    job_id=context.job_id,
                    parameters={
                        'task_number': i + 1,
                        'message': message,
                        'total_tasks': n,
                        'greeting': f"Hello from task_{i+1}!"
                    }
                )
                tasks.append(task_def)
            
        elif context.stage_number == 2:
            # Stage 2: Worlds Reply - Create response tasks
            self.logger.info(f"Creating {n} reply tasks for Stage 2")
            
            # Get stage 1 results for reply generation
            stage1_results = context.previous_stage_results or {}
            stage1_greetings = stage1_results.get('greetings', [])
            
            for i in range(n):
                task_id = f"{context.job_id}_stage2_task{i+1}"
                
                # Create reply to corresponding stage 1 task
                corresponding_greeting = (
                    stage1_greetings[i] if i < len(stage1_greetings) 
                    else f"Hello from task_{i+1}!"
                )
                
                task_def = TaskDefinition(
                    task_id=task_id,
                    task_type="hello_world_reply",
                    stage_number=2,
                    job_id=context.job_id,
                    parameters={
                        'task_number': i + 1,
                        'total_tasks': n,
                        'replying_to': corresponding_greeting,
                        'reply': f"Hello task_{i+1} from reply_task_{i+1}!"
                    }
                )
                tasks.append(task_def)
        
        else:
            raise ValueError(f"Unknown stage number: {context.stage_number}")
        
        self.logger.info(f"Created {len(tasks)} tasks for stage {context.stage_number}")
        return tasks
    
    def aggregate_job_results(self, context: JobExecutionContext) -> Dict[str, Any]:
        """
        Aggregate results from both stages into comprehensive job result.
        
        Updated to work with enhanced BaseController architecture:
        - Uses context.stage_results with proper task_results structure
        - Extracts results from TaskResult objects in stage_results
        - Creates comprehensive hello world statistics
        - Leverages new BaseController visibility methods
        """
        self.logger.info(f"Aggregating Hello World results for job {context.job_id[:16]}... with enhanced architecture")
        
        # Use enhanced BaseController methods for better visibility
        task_progress = self.get_task_progress(context.job_id)
        stage_status = self.get_stage_status(context.job_id)
        
        self.logger.debug(f"Task progress: {task_progress['overall']['completion_percentage']:.1f}% complete")
        self.logger.debug(f"Stage status: {stage_status}")
        
        # Extract results from stage_results (now contains task_results arrays)
        stage1_data = context.stage_results.get(1, {})
        stage2_data = context.stage_results.get(2, {})
        
        # Extract task results from each stage
        stage1_task_results = stage1_data.get('task_results', [])
        stage2_task_results = stage2_data.get('task_results', [])
        
        # Extract greetings and replies from task results
        stage1_greetings = []
        for task_result in stage1_task_results:
            if task_result.get('status') == 'completed':
                result_data = task_result.get('result_data', {})
                if isinstance(result_data, dict):
                    greeting = result_data.get('greeting') or result_data.get('enhanced_greeting')
                    if greeting:
                        stage1_greetings.append(greeting)
        
        stage2_replies = []
        for task_result in stage2_task_results:
            if task_result.get('status') == 'completed':
                result_data = task_result.get('result_data', {})
                if isinstance(result_data, dict):
                    reply = result_data.get('reply') or result_data.get('contextual_reply')
                    if reply:
                        stage2_replies.append(reply)
        
        # Get n parameter from context
        n = context.parameters.get('n', 1)
        
        # Calculate enhanced statistics using BaseController data
        total_tasks = task_progress['overall']['total_tasks']
        completed_tasks = task_progress['overall']['completed_tasks']
        failed_tasks = task_progress['overall']['failed_tasks']
        
        hello_statistics = {
            'total_hellos_requested': n,  # Each stage creates n tasks
            'total_tasks_created': total_tasks,
            'stage1_tasks_completed': len(stage1_task_results),
            'stage2_tasks_completed': len(stage2_task_results),
            'stage1_greetings_extracted': len(stage1_greetings),
            'stage2_replies_extracted': len(stage2_replies),
            'hellos_completed_successfully': completed_tasks,
            'hellos_failed': failed_tasks,
            'success_rate': round((completed_tasks / total_tasks * 100) if total_tasks > 0 else 0, 1),
            'overall_completion_percentage': task_progress['overall']['completion_percentage']
        }
        
        # Add failed task details if any
        failed_hello_numbers = []
        if failed_tasks > 0:
            for stage_num, stage_info in task_progress['stages'].items():
                if stage_info['failed_tasks'] > 0:
                    # Could extract specific task numbers that failed
                    failed_hello_numbers.extend([f"stage_{stage_num}_task_{i}" for i in range(stage_info['failed_tasks'])])
        
        hello_statistics['failed_hello_numbers'] = failed_hello_numbers
        
        # Create comprehensive result with enhanced architecture info
        job_result = {
            'job_id': context.job_id,
            'job_type': self.job_type,
            'completion_time': datetime.utcnow().isoformat(),
            'hello_statistics': hello_statistics,
            'stage_summary': {
                'total_stages': context.total_stages,
                'stage_status': stage_status,
                'stage1_status': stage_status.get(1, 'unknown'),
                'stage2_status': stage_status.get(2, 'unknown'),
                'completed_stages': len([s for s in stage_status.values() if 'completed' in s])
            },
            'hello_messages': stage1_greetings,
            'reply_messages': stage2_replies,
            'task_summary': {
                'total_tasks': total_tasks,
                'successful_tasks': completed_tasks,
                'failed_tasks': failed_tasks,
                'task_progress_by_stage': {stage_num: stage_info for stage_num, stage_info in task_progress['stages'].items()}
            },
            'workflow_demonstration': {
                'pattern': 'Hello Worlds → Worlds Reply (Enhanced Architecture)',
                'stage_sequence': 'Sequential execution with BaseController orchestration',
                'task_execution': 'Parallel within stages using TaskExecutionContext',
                'completion_detection': 'Enhanced "last task turns out lights" with explicit complete_job()',
                'result_aggregation': 'Comprehensive job-level summary with task visibility',
                'architecture_features': [
                    'Task progress monitoring',
                    'Stage status tracking', 
                    'Explicit job completion',
                    'Enhanced visibility methods'
                ]
            }
        }
        
        # Add failure details using enhanced architecture
        if hello_statistics['hellos_failed'] > 0:
            job_result['failed_tasks_details'] = {
                'count': hello_statistics['hellos_failed'],
                'failed_task_identifiers': failed_hello_numbers,
                'failure_breakdown_by_stage': {
                    stage_num: stage_info['failed_tasks'] 
                    for stage_num, stage_info in task_progress['stages'].items() 
                    if stage_info['failed_tasks'] > 0
                }
            }
        
        self.logger.info(f"✅ Hello World job aggregation complete using enhanced architecture: "
                        f"{hello_statistics['hellos_completed_successfully']}/{hello_statistics['total_tasks_created']} "
                        f"tasks successful ({hello_statistics['success_rate']}%)")
        
        return job_result

    # ========================================================================
    # HELLO WORLD SPECIFIC METHODS - Enhanced with new BaseController features
    # ========================================================================

    def get_hello_world_progress(self, job_id: str) -> Dict[str, Any]:
        """
        Get Hello World specific progress information.
        
        Combines BaseController progress with Hello World domain knowledge.
        
        Args:
            job_id: The job identifier
            
        Returns:
            Hello World specific progress with greeting/reply details
        """
        # Use BaseController progress method
        base_progress = self.get_task_progress(job_id)
        stage_status = self.get_stage_status(job_id)
        
        # Add Hello World domain information
        hello_progress = {
            **base_progress,
            'hello_world_info': {
                'workflow_pattern': 'Hello Worlds → Worlds Reply',
                'stage_1_purpose': 'Generate greeting messages',
                'stage_2_purpose': 'Generate reply messages using stage 1 results',
                'expected_stages': 2,
                'current_stage_names': {
                    1: 'Hello Worlds (Greeting Generation)',
                    2: 'Worlds Reply (Reply Generation)'
                }
            },
            'hello_specific_status': {
                'greeting_stage_status': stage_status.get(1, 'pending'),
                'reply_stage_status': stage_status.get(2, 'pending'),
                'ready_for_reply_stage': stage_status.get(1) in ['completed', 'completed_with_errors']
            }
        }
        
        self.logger.debug(f"Hello World progress for {job_id[:16]}...: "
                         f"Stage 1: {hello_progress['hello_specific_status']['greeting_stage_status']}, "
                         f"Stage 2: {hello_progress['hello_specific_status']['reply_stage_status']}")
        
        return hello_progress

    def get_hello_messages(self, job_id: str) -> Dict[str, List[str]]:
        """
        Extract hello messages and replies from completed tasks.
        
        Uses BaseController task listing to find and extract messages.
        
        Args:
            job_id: The job identifier
            
        Returns:
            Dictionary with greeting and reply messages
        """
        # Get all tasks using BaseController method
        tasks_by_stage = self.get_job_tasks(job_id)
        
        greetings = []
        replies = []
        
        # Extract greetings from Stage 1 tasks
        stage1_tasks = tasks_by_stage.get(1, [])
        for task in stage1_tasks:
            if task.get('status') == 'completed':
                result_data = task.get('result_data', {})
                if isinstance(result_data, str):
                    try:
                        import json
                        result_data = json.loads(result_data)
                    except:
                        pass
                
                if isinstance(result_data, dict):
                    greeting = result_data.get('greeting') or result_data.get('enhanced_greeting')
                    if greeting:
                        greetings.append(greeting)
        
        # Extract replies from Stage 2 tasks
        stage2_tasks = tasks_by_stage.get(2, [])
        for task in stage2_tasks:
            if task.get('status') == 'completed':
                result_data = task.get('result_data', {})
                if isinstance(result_data, str):
                    try:
                        import json
                        result_data = json.loads(result_data)
                    except:
                        pass
                
                if isinstance(result_data, dict):
                    reply = result_data.get('reply') or result_data.get('contextual_reply')
                    if reply:
                        replies.append(reply)
        
        messages = {
            'greetings': greetings,
            'replies': replies,
            'total_messages': len(greetings) + len(replies),
            'extraction_summary': {
                'stage1_tasks_checked': len(stage1_tasks),
                'stage2_tasks_checked': len(stage2_tasks),
                'greetings_found': len(greetings),
                'replies_found': len(replies)
            }
        }
        
        self.logger.debug(f"Extracted {len(greetings)} greetings and {len(replies)} replies from job {job_id[:16]}...")
        return messages

    def demonstrate_enhanced_controller_features(self, job_id: str) -> Dict[str, Any]:
        """
        Demonstrate all the enhanced BaseController features for Hello World.
        
        This method showcases the new capabilities added to BaseController.
        
        Args:
            job_id: The job identifier
            
        Returns:
            Comprehensive demonstration of all enhanced features
        """
        self.logger.info(f"Demonstrating enhanced controller features for Hello World job {job_id[:16]}...")
        
        demonstration = {
            'job_id': job_id,
            'controller_type': self.__class__.__name__,
            'enhanced_features': {},
            'demonstration_timestamp': datetime.utcnow().isoformat()
        }
        
        try:
            # 1. Stage listing
            demonstration['enhanced_features']['stage_listing'] = {
                'method': 'list_job_stages()',
                'result': self.list_job_stages(),
                'description': 'Lists all workflow stages with metadata'
            }
            
            # 2. Task progress
            demonstration['enhanced_features']['task_progress'] = {
                'method': 'get_task_progress(job_id)',
                'result': self.get_task_progress(job_id),
                'description': 'Detailed progress metrics by stage and overall'
            }
            
            # 3. Stage status
            demonstration['enhanced_features']['stage_status'] = {
                'method': 'get_stage_status(job_id)',
                'result': self.get_stage_status(job_id),
                'description': 'Completion status of each stage'
            }
            
            # 4. Completed stages
            demonstration['enhanced_features']['completed_stages'] = {
                'method': 'get_completed_stages(job_id)',
                'result': self.get_completed_stages(job_id),
                'description': 'List of completed stage numbers'
            }
            
            # 5. Task listing by stage
            demonstration['enhanced_features']['tasks_by_stage'] = {
                'method': 'get_job_tasks(job_id)',
                'result': {stage: len(tasks) for stage, tasks in self.get_job_tasks(job_id).items()},
                'description': 'Task counts by stage (full task details available)'
            }
            
            # 6. Hello World specific features
            demonstration['enhanced_features']['hello_world_specific'] = {
                'method': 'get_hello_world_progress(job_id)',
                'result': self.get_hello_world_progress(job_id)['hello_world_info'],
                'description': 'Hello World domain-specific progress information'
            }
            
            # 7. Message extraction
            demonstration['enhanced_features']['message_extraction'] = {
                'method': 'get_hello_messages(job_id)',
                'result': self.get_hello_messages(job_id)['extraction_summary'],
                'description': 'Extracted greeting and reply messages from completed tasks'
            }
            
            demonstration['summary'] = {
                'total_enhanced_methods': len(demonstration['enhanced_features']),
                'architecture_benefits': [
                    'Complete job visibility',
                    'Stage-by-stage progress tracking',
                    'Task-level monitoring',
                    'Explicit completion flow',
                    'Domain-specific extensions',
                    'Comprehensive result aggregation'
                ],
                'demonstration_success': True
            }
            
            self.logger.info(f"✅ Enhanced controller features demonstration complete for {job_id[:16]}...")
            
        except Exception as e:
            demonstration['error'] = {
                'message': str(e),
                'error_type': type(e).__name__,
                'demonstration_success': False
            }
            self.logger.error(f"❌ Error during enhanced features demonstration: {e}")
        
        return demonstration