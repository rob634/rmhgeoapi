"""
HelloWorldController - Redesign Architecture Test Implementation

Implements the foundational Job→Stage→Task architecture using a two-stage
"Hello Worlds → Worlds Reply" pattern as specified in the implementation plan.

This controller demonstrates:
- Sequential stage processing (Stage 1 → Stage 2)
- Parallel task execution within each stage
- "Last task turns out the lights" completion pattern
- Job result aggregation across all stages
- The n parameter for controlling parallel task creation
"""

from typing import List, Dict, Any
import logging
from datetime import datetime

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
        self.logger = logging.getLogger("HelloWorldController")
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
        
        Creates detailed statistics and summaries from all Hello World stages.
        """
        self.logger.info(f"Aggregating results for Hello World job {context.job_id}")
        
        # Get results from both stages
        stage1_results = context.get_stage_result(1) or {}
        stage2_results = context.get_stage_result(2) or {}
        
        # Extract greetings and replies
        stage1_greetings = stage1_results.get('greetings', [])
        stage2_replies = stage2_results.get('replies', [])
        
        n = context.parameters.get('n', 1)
        
        # Calculate statistics
        hello_statistics = {
            'total_hellos_requested': n * 2,  # Both greeting and reply tasks
            'stage1_hellos_completed': len(stage1_greetings),
            'stage2_replies_completed': len(stage2_replies),
            'hellos_completed_successfully': len(stage1_greetings) + len(stage2_replies),
            'hellos_failed': (n * 2) - (len(stage1_greetings) + len(stage2_replies)),
            'success_rate': round(((len(stage1_greetings) + len(stage2_replies)) / (n * 2)) * 100, 1)
        }
        
        # Create comprehensive result
        job_result = {
            'job_id': context.job_id,
            'job_type': self.job_type,
            'completion_time': datetime.utcnow().isoformat(),
            'hello_statistics': hello_statistics,
            'stage_summary': {
                'total_stages': context.total_stages,
                'completed_stages': len([r for r in [stage1_results, stage2_results] if r]),
                'stage1_status': 'completed' if stage1_results else 'failed',
                'stage2_status': 'completed' if stage2_results else 'failed'
            },
            'hello_messages': stage1_greetings,
            'reply_messages': stage2_replies,
            'workflow_demonstration': {
                'pattern': 'Hello Worlds → Worlds Reply',
                'stage_sequence': 'Sequential execution',
                'task_execution': 'Parallel within stages',
                'completion_detection': 'Last task turns out the lights',
                'result_aggregation': 'Comprehensive job-level summary'
            }
        }
        
        # Add failure details if any
        if hello_statistics['hellos_failed'] > 0:
            job_result['failed_tasks'] = {
                'count': hello_statistics['hellos_failed'],
                'stage1_failures': n - len(stage1_greetings),
                'stage2_failures': n - len(stage2_replies)
            }
        
        self.logger.info(f"Hello World job aggregation complete: "
                        f"{hello_statistics['hellos_completed_successfully']}/{hello_statistics['total_hellos_requested']} "
                        f"tasks successful ({hello_statistics['success_rate']}%)")
        
        return job_result