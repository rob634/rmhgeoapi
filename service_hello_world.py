"""
Hello World Tasks - Redesign Architecture Test Implementation

Implements the business logic tasks for the Hello World → Worlds Reply workflow.
These tasks demonstrate the Service + Repository layer responsibility within
the Job→Stage→Task architecture.

Task Types:
1. HelloWorldGreetingTask - Creates greeting messages in Stage 1
2. HelloWorldReplyTask - Creates reply messages in Stage 2
"""

from typing import Dict, Any
import logging
import time
from datetime import datetime

from model_task_base import BaseTask
from model_core import TaskStatus, TaskExecutionContext, TaskResult


class HelloWorldGreetingTask(BaseTask):
    """
    Task for Stage 1: Hello Worlds
    
    Creates greeting messages of the form "Hello from task_{i}!"
    Simulates the business logic layer within the redesigned architecture.
    """
    
    def __init__(self):
        super().__init__("hello_world_greeting")
        self.logger = logging.getLogger("HelloWorldGreetingTask")
    
    def validate_task_parameters(self, context: TaskExecutionContext) -> bool:
        """Validate greeting task parameters"""
        required_params = ['task_number', 'message', 'greeting']
        
        for param in required_params:
            if param not in context.parameters:
                self.logger.error(f"Missing required parameter: {param}")
                return False
        
        task_number = context.parameters.get('task_number')
        if not isinstance(task_number, int) or task_number < 1:
            self.logger.error(f"Invalid task_number: {task_number}")
            return False
        
        return True
    
    def execute(self, context: TaskExecutionContext) -> TaskResult:
        """
        Execute greeting task - creates a Hello World greeting.
        
        This simulates the Service + Repository layer work:
        - Processing input parameters
        - Performing business logic (creating greeting)
        - Returning structured result
        """
        start_time = time.time()
        
        try:
            # Extract parameters
            task_number = context.parameters['task_number']
            message_prefix = context.parameters['message']
            total_tasks = context.parameters.get('total_tasks', 1)
            
            self.logger.info(f"Executing greeting task {task_number}/{total_tasks} for job {context.job_id}")
            
            # Simulate some processing time (0.1-0.5 seconds)
            processing_time = 0.1 + (task_number * 0.05) % 0.4
            time.sleep(processing_time)
            
            # Create the greeting (business logic)
            greeting_text = f"Hello from task_{task_number}!"
            enhanced_greeting = f"{message_prefix}: {greeting_text}"
            
            # Create result data
            result_data = {
                'task_number': task_number,
                'greeting': greeting_text,
                'enhanced_greeting': enhanced_greeting,
                'message_prefix': message_prefix,
                'stage': 'hello_worlds',
                'total_tasks_in_stage': total_tasks,
                'success': True,
                'processed_items': 1,
                'execution_time_seconds': time.time() - start_time
            }
            
            self.logger.info(f"Greeting task {task_number} completed: '{greeting_text}'")
            
            return TaskResult(
                task_id=context.task_id,
                job_id=context.job_id,
                stage_number=context.stage_number,
                task_type=self.task_type,
                status=TaskStatus.COMPLETED,
                result=result_data,
                execution_time_seconds=time.time() - start_time,
                processed_items=1,
                completed_at=datetime.utcnow().isoformat()
            )
            
        except Exception as e:
            self.logger.error(f"Greeting task {context.task_id} failed: {e}", exc_info=True)
            
            return TaskResult(
                task_id=context.task_id,
                job_id=context.job_id,
                stage_number=context.stage_number,
                task_type=self.task_type,
                status=TaskStatus.FAILED,
                error=str(e),
                execution_time_seconds=time.time() - start_time
            )


class HelloWorldReplyTask(BaseTask):
    """
    Task for Stage 2: Worlds Reply
    
    Creates reply messages responding to Stage 1 greetings.
    Demonstrates inter-stage data passing in the redesigned architecture.
    """
    
    def __init__(self):
        super().__init__("hello_world_reply")
        self.logger = logging.getLogger("HelloWorldReplyTask")
    
    def validate_task_parameters(self, context: TaskExecutionContext) -> bool:
        """Validate reply task parameters"""
        required_params = ['task_number', 'replying_to', 'reply']
        
        for param in required_params:
            if param not in context.parameters:
                self.logger.error(f"Missing required parameter: {param}")
                return False
        
        task_number = context.parameters.get('task_number')
        if not isinstance(task_number, int) or task_number < 1:
            self.logger.error(f"Invalid task_number: {task_number}")
            return False
        
        return True
    
    def execute(self, context: TaskExecutionContext) -> TaskResult:
        """
        Execute reply task - creates a response to Stage 1 greeting.
        
        This demonstrates:
        - Inter-stage data usage (replying_to parameter from Stage 1)
        - Business logic processing (creating personalized reply)
        - Result structuring for job-level aggregation
        """
        start_time = time.time()
        
        try:
            # Extract parameters
            task_number = context.parameters['task_number']
            replying_to = context.parameters['replying_to']
            total_tasks = context.parameters.get('total_tasks', 1)
            
            self.logger.info(f"Executing reply task {task_number}/{total_tasks} for job {context.job_id}")
            self.logger.debug(f"Replying to: '{replying_to}'")
            
            # Simulate some processing time (0.1-0.3 seconds)
            processing_time = 0.1 + (task_number * 0.02) % 0.2
            time.sleep(processing_time)
            
            # Create the reply (business logic with inter-stage data)
            reply_text = f"Hello task_{task_number} from reply_task_{task_number}!"
            contextual_reply = f"Received '{replying_to}' - {reply_text}"
            
            # Create result data
            result_data = {
                'task_number': task_number,
                'reply': reply_text,
                'contextual_reply': contextual_reply,
                'original_greeting': replying_to,
                'stage': 'worlds_reply',
                'total_tasks_in_stage': total_tasks,
                'inter_stage_processing': True,
                'success': True,
                'processed_items': 1,
                'execution_time_seconds': time.time() - start_time
            }
            
            self.logger.info(f"Reply task {task_number} completed: '{reply_text}'")
            
            return TaskResult(
                task_id=context.task_id,
                job_id=context.job_id,
                stage_number=context.stage_number,
                task_type=self.task_type,
                status=TaskStatus.COMPLETED,
                result=result_data,
                execution_time_seconds=time.time() - start_time,
                processed_items=1,
                completed_at=datetime.utcnow().isoformat()
            )
            
        except Exception as e:
            self.logger.error(f"Reply task {context.task_id} failed: {e}", exc_info=True)
            
            return TaskResult(
                task_id=context.task_id,
                job_id=context.job_id,
                stage_number=context.stage_number,
                task_type=self.task_type,
                status=TaskStatus.FAILED,
                error=str(e),
                execution_time_seconds=time.time() - start_time
            )


# Task Registry for routing task types to implementations
HELLO_WORLD_TASKS = {
    'hello_world_greeting': HelloWorldGreetingTask,
    'hello_world_reply': HelloWorldReplyTask
}


def get_hello_world_task(task_type: str) -> BaseTask:
    """
    Factory function to get Hello World task instances.
    
    Args:
        task_type: The type of Hello World task to create
        
    Returns:
        BaseTask instance for the specified task type
        
    Raises:
        ValueError: If task type is not supported
    """
    if task_type not in HELLO_WORLD_TASKS:
        raise ValueError(f"Unsupported Hello World task type: {task_type}")
    
    task_class = HELLO_WORLD_TASKS[task_type]
    return task_class()