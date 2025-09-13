# ============================================================================
# CLAUDE CONTEXT - CONTROLLER
# ============================================================================
# PURPOSE: HelloWorld workflow controller using new registry pattern - demonstrates two-stage orchestration
# EXPORTS: HelloWorldController (concrete controller with decorator-based registration)
# INTERFACES: BaseController from schema_base - implements abstract methods for workflow orchestration
# PYDANTIC_MODELS: WorkflowDefinition, StageDefinition, TaskDefinition, TaskResult
# DEPENDENCIES: schema_base, job_factory, util_logger, typing, datetime
# SOURCE: Job parameters from HTTP requests, workflow from decorator registration
# SCOPE: HelloWorld-specific workflow with greeting and reply stages
# VALIDATION: Parameter validation (n must be integer), workflow validation via Pydantic
# PATTERNS: Decorator registration, Template Method, Factory pattern for task creation
# ENTRY_POINTS: Automatically registered via @JobRegistry decorator at import
# INDEX: HelloWorldWorkflow:50, HelloWorldController:100, create_stage_tasks:150
# ============================================================================

"""
HelloWorld Controller - New Registry Pattern Implementation

Updated HelloWorld controller using the new decorator-based registration pattern
with JobRegistry. Demonstrates the complete Job→Stage→Task orchestration with
proper workflow definition and factory patterns.

This is the reference implementation for all new controllers, showing:
- Decorator-based registration with JobRegistry
- WorkflowDefinition with validated stages
- BaseController.generate_task_id() for semantic task ID generation
- Proper stage advancement and result aggregation
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from controller_base import BaseController
from schema_base import (
    JobRegistry,
    WorkflowDefinition,
    StageDefinition,
    TaskDefinition,
    TaskResult,
    TaskStatus
)
# TaskFactory import removed - using BaseController.generate_task_id() instead
from util_logger import LoggerFactory
from util_logger import ComponentType, LogLevel, LogContext


# ============================================================================
# WORKFLOW DEFINITION
# ============================================================================

# Define the HelloWorld workflow
hello_world_workflow = WorkflowDefinition(
    job_type="hello_world",
    description="Two-stage greeting and reply workflow demonstration",
    total_stages=2,
    stages=[
        StageDefinition(
            stage_number=1,
            stage_name="greeting",
            task_type="hello_world_greeting",
            max_parallel_tasks=10,
            timeout_minutes=5
        ),
        StageDefinition(
            stage_number=2,
            stage_name="reply",
            task_type="hello_world_reply",
            max_parallel_tasks=10,
            timeout_minutes=5,
            depends_on_stage=1,
            is_final_stage=True
        )
    ]
)


# ============================================================================
# CONTROLLER IMPLEMENTATION
# ============================================================================

@JobRegistry.instance().register(
    job_type="hello_world",
    workflow=hello_world_workflow,
    description="HelloWorld demonstration with greeting and reply stages",
    max_parallel_tasks=20,
    timeout_minutes=10
)
class HelloWorldController(BaseController):
    """
    HelloWorld controller with new registry pattern.
    
    Implements a two-stage workflow:
    1. Greeting Stage: Creates n parallel tasks saying "Hello from task_{i}!"
    2. Reply Stage: Creates n parallel tasks responding with "World replies to task_{i}!"
    
    Demonstrates:
    - Decorator-based registration
    - Validated workflow definition
    - Task factory pattern
    - Inter-stage data passing
    - Result aggregation
    """
    
    def __init__(self):
        """
        Initialize HelloWorld controller.
        
        Note: Workflow is injected by the decorator, not defined here.
        """
        super().__init__()
        self.logger = LoggerFactory.create_logger(
            ComponentType.CONTROLLER, 
            "HelloWorldController"
        )
    
    def get_job_type(self) -> str:
        """
        Return the job type for HelloWorld controller.
        
        Returns:
            str: "hello_world"
        """
        return "hello_world"
    
    def validate_job_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate HelloWorld job parameters.
        
        Args:
            parameters: Must contain 'n' (number of tasks) and optionally 'name' (greeting target)
            
        Returns:
            Dict[str, Any]: Validated and normalized parameters
            
        Raises:
            ValueError: If parameters are invalid
        """
        if 'n' not in parameters:
            raise ValueError("Parameter 'n' is required (number of tasks to create)")
        
        n = parameters['n']
        if not isinstance(n, int) or n < 1 or n > 100:
            raise ValueError("Parameter 'n' must be an integer between 1 and 100")
        
        # Create normalized parameters dictionary
        validated_params = {
            'n': n,
            'name': parameters.get('name', 'World')  # Default to 'World'
        }
        
        # Preserve any additional parameters like 'message'
        for key, value in parameters.items():
            if key not in validated_params and key not in ['dataset_id', 'resource_id', 'version_id', 'system']:
                validated_params[key] = value
        
        self.logger.info(f"✅ Validated HelloWorld job: n={n}, name={validated_params['name']}")
        return validated_params
    
    def create_stage_tasks(
        self,
        stage_number: int,
        job_id: str,
        job_parameters: Dict[str, Any],
        previous_stage_results: Optional[Dict[str, Any]] = None
    ) -> List[TaskDefinition]:
        """
        Create tasks for the specified stage.
        
        Args:
            stage_number: 1 for greeting, 2 for reply
            job_id: Parent job ID
            job_parameters: Contains 'n' and 'name'
            previous_stage_results: Results from stage 1 when creating stage 2
            
        Returns:
            List of TaskDefinition objects
        """
        tasks = []
        n = job_parameters['n']
        name = job_parameters.get('name', 'World')
        
        if stage_number == 1:
            # Greeting stage - create n greeting tasks
            self.logger.info(f"Creating {n} greeting tasks for job {job_id[:8]}")
            
            for i in range(n):
                task_id = self.generate_task_id(job_id, stage_number, f"greet-{i}")
                
                tasks.append(TaskDefinition(
                    task_id=task_id,
                    job_type="hello_world",  # Added for controller routing
                    task_type="hello_world_greeting",
                    stage_number=stage_number,
                    job_id=job_id,
                    parameters={
                        'task_index': f'greet_{i}',
                        'task_number': i,
                        'name': name,
                        'message': f"Hello {name} from task {i}!",
                        # Set up handoff for next stage
                        'next_stage_params': {
                            'greeting': f"Hello {name} from task {i}!"
                        }
                    }
                ))
                
        elif stage_number == 2:
            # Reply stage - create n reply tasks
            self.logger.info(f"Creating {n} reply tasks for job {job_id[:8]}")
            
            for i in range(n):
                task_id = self.generate_task_id(job_id, stage_number, f"reply-{i}")
                
                # Get greeting from previous stage if available
                greeting = "Hello"
                if previous_stage_results and 'greetings' in previous_stage_results:
                    greetings = previous_stage_results['greetings']
                    if i < len(greetings):
                        greeting = greetings[i]
                
                tasks.append(TaskDefinition(
                    task_id=task_id,
                    job_type="hello_world",  # Added for controller routing
                    task_type="hello_world_reply",
                    stage_number=stage_number,
                    job_id=job_id,
                    parameters={
                        'task_index': f'reply_{i}',
                        'task_number': i,
                        'original_greeting': greeting,
                        'reply': f"World replies to: {greeting}",
                        'parent_task_id': self.generate_task_id(
                            job_id, 1, f"greet_{i}"
                        )  # Reference to corresponding greeting task
                    }
                ))
        
        return tasks
    
    def aggregate_stage_results(
        self,
        stage_number: int,
        task_results: List[TaskResult]
    ) -> Dict[str, Any]:
        """
        Aggregate results from all tasks in a stage.
        
        Args:
            stage_number: The stage that completed
            task_results: Results from all tasks
            
        Returns:
            Aggregated results to store and pass to next stage
        """
        self.logger.info(
            f"Aggregating {len(task_results)} task results for stage {stage_number}"
        )
        
        # Count successes and failures (handle string status due to use_enum_values)
        successful = [t for t in task_results if t.success]
        failed = [t for t in task_results if not t.success]
        
        # Aggregate based on stage
        if stage_number == 1:
            # Greeting stage - collect all greetings
            greetings = []
            for task in successful:
                if task.result_data and 'message' in task.result_data:
                    greetings.append(task.result_data['message'])
            
            return {
                'stage': 'greeting',
                'task_count': len(task_results),
                'successful': len(successful),
                'failed': len(failed),
                'greetings': greetings,
                'execution_time': sum(t.execution_time_seconds for t in task_results),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            
        elif stage_number == 2:
            # Reply stage - collect all replies
            replies = []
            for task in successful:
                if task.result_data and 'reply' in task.result_data:
                    replies.append(task.result_data['reply'])
            
            return {
                'stage': 'reply',
                'task_count': len(task_results),
                'successful': len(successful),
                'failed': len(failed),
                'replies': replies,
                'execution_time': sum(t.execution_time_seconds for t in task_results),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
        
        return {
            'stage': stage_number,
            'task_count': len(task_results),
            'successful': len(successful),
            'failed': len(failed)
        }
    
    def should_advance_stage(
        self,
        stage_number: int,
        stage_results: Dict[str, Any]
    ) -> bool:
        """
        Determine if job should advance to next stage.
        
        For HelloWorld, we advance if at least one task succeeded.
        In production, this might require higher success rates.
        
        Args:
            stage_number: Current stage
            stage_results: Aggregated results
            
        Returns:
            bool: True to advance, False to fail job
        """
        # Require at least one successful task to advance
        successful_count = stage_results.get('successful', 0)
        
        if successful_count == 0:
            self.logger.error(
                f"Stage {stage_number} failed - no successful tasks"
            )
            return False
        
        # Could add more sophisticated logic here
        # For example, require 80% success rate:
        # success_rate = successful_count / stage_results.get('task_count', 1)
        # if success_rate < 0.8:
        #     return False
        
        self.logger.info(
            f"Stage {stage_number} completed with {successful_count} successful tasks"
        )
        return True
    
    def aggregate_job_results(self, context) -> Dict[str, Any]:
        """
        Aggregate all stage results into final job result.
        
        Args:
            context: Job execution context with all stage results
            
        Returns:
            Final aggregated job result
        """
        # Simple aggregation for HelloWorld - combine all stage results
        return {
            'job_type': 'hello_world',
            'job_id': context.job_id if hasattr(context, 'job_id') else 'unknown',
            'total_stages': len(context.stage_results) if hasattr(context, 'stage_results') else 0,
            'stage_results': context.stage_results if hasattr(context, 'stage_results') else {},
            'final_status': 'completed',
            'completed_at': datetime.now(timezone.utc).isoformat()
        }


# ============================================================================
# MODULE INITIALIZATION
# ============================================================================

# The controller is automatically registered when this module is imported
# No need for explicit registration calls

"""
Usage Example:

from controller_factories import JobFactory

# Create controller via factory
controller = JobFactory.create_controller("hello_world")

# Create tasks for stage 1
tasks = controller.create_stage_tasks(
    stage_number=1,
    job_id="abc123...",
    job_parameters={'n': 5, 'name': 'Azure'}
)

# Tasks are created and can be sent to queue
"""