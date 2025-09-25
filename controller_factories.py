# ============================================================================
# CLAUDE CONTEXT - CONTROLLER
# ============================================================================
# PURPOSE: Factory classes for creating controllers and tasks in the job orchestration system
# EXPORTS: JobFactory, TaskFactory
# INTERFACES: Factory pattern for job/task instantiation
# PYDANTIC_MODELS: Uses models from schema_base
# DEPENDENCIES: schema_base, typing, hashlib, importlib
# SOURCE: JobRegistry singleton for job type lookup
# SCOPE: Job and task creation throughout the system
# VALIDATION: Validates job types against registry, generates deterministic IDs
# PATTERNS: Factory pattern, Singleton registry access
# ENTRY_POINTS: JobFactory.create_controller(), TaskFactory.create_tasks()
# INDEX: JobFactory:50, TaskFactory:150
# ============================================================================

"""
Job and Task Factory Classes

This module provides factory classes for creating controllers and tasks in the
Azure Geospatial ETL Pipeline. It implements the factory pattern to instantiate
the correct controller based on job type and bulk-create tasks for stages.

Key Components:
- JobFactory: Creates controller instances from registered job types
- TaskFactory: Bulk creates task records and queue messages

The factories work with the JobRegistry to ensure only registered job types
can be instantiated and provide consistent task ID generation.
"""

import hashlib
import importlib
from typing import List, Dict, Any, Optional, Tuple, Type
from datetime import datetime, timezone

from controller_base import BaseController
from schema_base import (
    WorkflowDefinition,
    TaskDefinition,
    TaskRecord,
    TaskStatus
)
from schema_queue import JobQueueMessage, TaskQueueMessage
from registration import JobCatalog  # Import the new catalog


# ============================================================================
# JOB FACTORY - Controller instantiation
# ============================================================================

class JobFactory:
    """
    Factory for creating job controllers.

    Uses the JobCatalog to instantiate the correct controller for a given
    job type. Ensures type safety and proper initialization of controllers
    with their workflow definitions.
    """

    _catalog: Optional[JobCatalog] = None
    
    @classmethod
    def set_catalog(cls, catalog: JobCatalog) -> None:
        """Set the job catalog instance to use."""
        cls._catalog = catalog

    @staticmethod
    def create_controller(job_type: str) -> BaseController:
        """
        Create a controller instance for the specified job type.

        Args:
            job_type: The type of job to create a controller for

        Returns:
            Instantiated controller with workflow attached

        Raises:
            ValueError: If job_type is not registered
            RuntimeError: If catalog not initialized
        """
        if JobFactory._catalog is None:
            raise RuntimeError("JobCatalog not initialized. Call JobFactory.set_catalog() first.")

        # Get controller class from catalog
        controller_class = JobFactory._catalog.get_controller(job_type)

        # Get metadata for injection
        metadata = JobFactory._catalog.get_metadata(job_type)

        # Create instance
        controller = controller_class()

        # Inject metadata
        controller._job_type = job_type
        if 'workflow' in metadata:
            controller._workflow = metadata['workflow']

        return controller
    
    
    @staticmethod
    def list_available_jobs() -> List[str]:
        """List available job types from catalog."""
        if JobFactory._catalog is None:
            return []  # Return empty list if catalog not initialized
        return JobFactory._catalog.list_job_types()

    @staticmethod
    def get_workflow(job_type: str) -> WorkflowDefinition:
        """
        Get workflow definition without instantiating controller.

        Useful for validation and planning without creating objects.

        Args:
            job_type: The job type to get workflow for

        Returns:
            WorkflowDefinition for the job type

        Raises:
            ValueError: If job_type is not registered
        """
        if JobFactory._catalog is None:
            raise RuntimeError("JobCatalog not initialized. Call JobFactory.set_catalog() first.")

        # Get from catalog
        metadata = JobFactory._catalog.get_metadata(job_type)
        if 'workflow' in metadata:
            return metadata['workflow']
        raise ValueError(f"No workflow found for job_type: '{job_type}'")


# ============================================================================
# TASK FACTORY - High-volume task creation
# ============================================================================

class TaskFactory:
    """
    Factory for creating potentially thousands of task instances.
    
    Handles bulk creation of TaskRecord and TaskQueueMessage objects with
    deterministic ID generation. Critical for stages that fan out to many
    parallel tasks (e.g., processing 1000 raster tiles).
    """
    
    @staticmethod
    def create_tasks(
        job_id: str,
        stage_number: int,
        task_type: str,
        task_params: List[Dict[str, Any]],
        parent_results: Optional[Dict[str, Any]] = None
    ) -> Tuple[List[TaskRecord], List[TaskQueueMessage]]:
        """
        Bulk create task records and queue messages.
        
        Creates all tasks for a stage in one operation, generating
        deterministic IDs and maintaining consistency between records
        and messages.
        
        Args:
            job_id: Parent job ID (SHA256 hash)
            stage_number: Stage number (1-based)
            task_type: Type of tasks to create
            task_params: List of parameter dicts, one per task
            parent_results: Results from previous stage
            
        Returns:
            Tuple of (task_records, queue_messages)
        """
        task_records = []
        queue_messages = []
        
        for index, params in enumerate(task_params):
            # Generate task ID - can be semantic or numeric
            task_index = params.get('task_index', str(index))
            task_id = TaskFactory.generate_task_id(
                job_id, stage_number, task_index
            )
            
            # Check for explicit task handoff
            parent_task_id = params.get('parent_task_id')
            
            # Create task record for database
            record = TaskRecord(
                task_id=task_id,
                parent_job_id=job_id,
                task_type=task_type,
                stage=stage_number,
                task_index=task_index,
                parameters=params,
                status=TaskStatus.QUEUED,
                next_stage_params=params.get('next_stage_params')
            )
            
            # Create corresponding queue message
            message = TaskQueueMessage(
                task_id=task_id,
                parent_job_id=job_id,
                task_type=task_type,
                stage=stage_number,
                task_index=task_index,
                parameters=params,
                parent_task_id=parent_task_id,
                timestamp=datetime.now(timezone.utc)
            )
            
            task_records.append(record)
            queue_messages.append(message)
        
        return task_records, queue_messages
    
    @staticmethod
    def generate_task_id(
        job_id: str, 
        stage_number: int, 
        task_index: str
    ) -> str:
        """
        Generate deterministic task ID with implicit lineage tracking.
        
        Creates a unique task ID that embeds job context and enables implicit
        data flow between stages. The ID structure allows tasks in stage N to
        automatically locate their predecessor data from stage N-1 using the
        same semantic index.
        
        Robert's Lineage Pattern:
        - Stage 1: a1b2c3d4-s1-tile_x12_y3 writes result_data
        - Stage 2: a1b2c3d4-s2-tile_x12_y3 reads s1 predecessor by ID pattern
        - Stage 3: a1b2c3d4-s3-tile_x12_y3 reads s2 predecessor by ID pattern
        
        This eliminates explicit handoff mechanisms while maintaining clear
        data lineage for parallel processing of tiles/chunks.
        
        Args:
            job_id: Parent job ID (SHA256)
            stage_number: Stage number (1-based)
            task_index: Semantic index (e.g., "tile_x5_y10", "chunk_42")
                       Must be consistent across stages for lineage
            
        Returns:
            Deterministic task ID like "a1b2c3d4-s2-tile_x5_y10"
            
        Author: Robert and Geospatial Claude Legion
        """
        # Option 1: Readable format (easier debugging)
        # Shows first 8 chars of job ID for correlation
        readable_id = f"{job_id[:8]}-s{stage_number}-{task_index}"
        
        # Ensure it fits in database field (100 chars max)
        if len(readable_id) <= 100:
            return readable_id
        
        # Option 2: Hash-based for long semantic indices
        content = f"{job_id}-{stage_number}-{task_index}"
        hash_id = hashlib.sha256(content.encode()).hexdigest()
        
        # Still include stage for debugging
        return f"{hash_id[:8]}-s{stage_number}-{hash_id[8:16]}"
    
    @staticmethod
    def create_tasks_from_definitions(
        definitions: List[TaskDefinition]
    ) -> Tuple[List[TaskRecord], List[TaskQueueMessage]]:
        """
        Create tasks from TaskDefinition objects.
        
        Alternative method that works with TaskDefinition objects
        created by controllers.
        
        Args:
            definitions: List of TaskDefinition objects
            
        Returns:
            Tuple of (task_records, queue_messages)
        """
        task_records = []
        queue_messages = []
        
        for defn in definitions:
            # Create task record
            record = TaskRecord(
                task_id=defn.task_id,
                parent_job_id=defn.job_id,
                task_type=defn.task_type,
                stage=defn.stage_number,
                task_index=str(defn.parameters.get('task_index', '0')),
                parameters=defn.parameters,
                status=TaskStatus.QUEUED,
                retry_count=defn.retry_count
            )
            
            # Create queue message
            message = TaskQueueMessage(
                task_id=defn.task_id,
                parent_job_id=defn.job_id,
                task_type=defn.task_type,
                stage=defn.stage_number,
                task_index=str(defn.parameters.get('task_index', '0')),
                parameters=defn.parameters,
                retry_count=defn.retry_count,
                timestamp=datetime.now(timezone.utc)
            )
            
            task_records.append(record)
            queue_messages.append(message)
        
        return task_records, queue_messages
    
    @staticmethod
    def create_continuation_job_message(
        job_id: str,
        job_type: str,
        next_stage: int,
        parameters: Dict[str, Any],
        stage_results: Dict[str, Any]
    ) -> JobQueueMessage:
        """
        Create a Jobs Queue message for stage continuation.
        
        Used when a stage completes and needs to trigger the next stage.
        This is critical for the "last task turns out the lights" pattern.
        
        Args:
            job_id: Job ID to continue
            job_type: Type of job
            next_stage: Stage number to execute
            parameters: Original job parameters
            stage_results: Results from completed stages
            
        Returns:
            JobQueueMessage for continuation
        """
        return JobQueueMessage(
            job_id=job_id,
            job_type=job_type,
            stage=next_stage,
            parameters=parameters,
            stage_results=stage_results,
            timestamp=datetime.now(timezone.utc)
        )


# ============================================================================
# USAGE EXAMPLES
# ============================================================================

"""
Example usage in controller:

@JobRegistry.instance().register(
    job_type="process_raster",
    workflow=workflow,
    description="Process raster into COGs"
)
class ProcessRasterController(BaseController):
    
    def create_stage_tasks(self, stage_number, job_id, params, prev_results):
        if stage_number == 2:  # Tiling stage
            # Calculate tiles (could be 100-1000)
            tile_params = []
            for x in range(10):
                for y in range(10):
                    tile_params.append({
                        'task_index': f'tile_x{x}_y{y}',
                        'bounds': [x*100, y*100, (x+1)*100, (y+1)*100],
                        'source_raster': params['input_path']
                    })
            
            # Use factory for bulk creation
            definitions = []
            for p in tile_params:
                task_id = TaskFactory.generate_task_id(
                    job_id, stage_number, p['task_index']
                )
                definitions.append(TaskDefinition(
                    task_id=task_id,
                    task_type='process_tile',
                    stage_number=stage_number,
                    job_id=job_id,
                    parameters=p
                ))
            
            return definitions

# In submit_job endpoint:
controller = JobFactory.create_controller(job_type)
workflow = JobFactory.get_workflow(job_type)

# When stage completes:
next_msg = TaskFactory.create_continuation_job_message(
    job_id, job_type, next_stage, params, stage_results
)
"""