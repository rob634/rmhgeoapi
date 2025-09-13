# ============================================================================
# CLAUDE CONTEXT - CONTROLLER
# ============================================================================
# PURPOSE: Container operation controllers implementing Job→Stage→Task orchestration for blob storage
# EXPORTS: SummarizeContainerController, ListContainerController (auto-registered with JobRegistry)
# INTERFACES: BaseController abstract methods for job orchestration
# PYDANTIC_MODELS: TaskDefinition, WorkflowDefinition from schema_base
# DEPENDENCIES: controller_base, job_registry, repository_factory, schema_blob, hashlib
# SOURCE: Job parameters from HTTP requests, stage results from task completions
# SCOPE: Job-level orchestration for container analysis and metadata extraction
# VALIDATION: Parameter validation, container size limits, task creation validation
# PATTERNS: Template Method (BaseController), Factory (JobRegistry), Dynamic Orchestration
# ENTRY_POINTS: Auto-registered via @JobRegistry decorators for 'summarize_container' and 'list_container'
# INDEX: SummarizeContainerController:100, ListContainerController:300, Dynamic Task Creation:450
# ============================================================================

"""
Container Operation Controllers

Controllers for blob storage container operations implementing the
Job→Stage→Task orchestration pattern with dynamic task generation.

Key Controllers:
- SummarizeContainerController: Generates container statistics
- ListContainerController: Lists and extracts metadata with dynamic orchestration

Architecture:
    Job Level: These controllers orchestrate the workflow
    Stage Level: Sequential execution with parallel tasks
    Task Level: Individual operations handled by service_blob.py

Dynamic Orchestration Pattern:
    The ListContainerController demonstrates the "Analyze & Orchestrate" pattern
    where Stage 1 analyzes the container and dynamically creates Stage 2 tasks
    based on actual content.

Author: Robert and Geospatial Claude Legion
Date: 9 December 2025
"""

# ============================================================================
# IMPORTS - Top of file for fail-fast behavior
# ============================================================================

# Standard library imports
import hashlib
from datetime import datetime
from typing import Dict, Any, List, Optional

# Application imports - Core controllers and registry
from controller_base import BaseController
from schema_base import JobRegistry, TaskResult

# Application imports - Schemas
from schema_base import TaskDefinition, StageDefinition, WorkflowDefinition
from schema_blob import ContainerSizeLimits, MetadataLevel

# Application imports - Logging
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, __name__)


# ============================================================================
# WORKFLOW DEFINITIONS
# ============================================================================

# Summarize container workflow
summarize_container_workflow = WorkflowDefinition(
    job_type="summarize_container",
    description="Generate statistics and summary for a storage container",
    total_stages=1,
    stages=[
        StageDefinition(
            stage_number=1,
            stage_name="summarize",
            task_type="summarize_container",
            max_parallel_tasks=1,
            timeout_minutes=5
        )
    ]
)

# List container workflow (dynamic multi-stage)
list_container_workflow = WorkflowDefinition(
    job_type="list_container",
    description="List container files with dynamic task generation for metadata extraction",
    total_stages=2,
    stages=[
        StageDefinition(
            stage_number=1,
            stage_name="analyze_orchestrate",
            task_type="analyze_and_orchestrate",
            max_parallel_tasks=1,
            timeout_minutes=2
        ),
        StageDefinition(
            stage_number=2,
            stage_name="extract_metadata",
            task_type="extract_metadata",
            max_parallel_tasks=100,
            timeout_minutes=1,
            depends_on_stage=1
        )
    ]
)


# ============================================================================
# SUMMARIZE CONTAINER CONTROLLER
# ============================================================================

@JobRegistry.instance().register(
    job_type="summarize_container",
    workflow=summarize_container_workflow,
    description="Generate container statistics and summary",
    max_parallel_tasks=1,
    timeout_minutes=10
)
class SummarizeContainerController(BaseController):
    """
    Controller for summarizing container contents.
    
    Generates statistics about file counts, sizes, and distributions.
    Can be single-stage for small containers or multi-stage for large ones.
    
    Workflow:
        Single Stage (< 2500 files):
            Stage 1: One task summarizes entire container
        
        Multi-Stage (future enhancement):
            Stage 1: Parallel analysis of container chunks
            Stage 2: Aggregation of chunk results
    """
    
    def __init__(self):
        """Initialize controller - workflow injected by decorator"""
        super().__init__()
        logger.info("Initialized SummarizeContainerController")
    
    def validate_job_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate container summarization parameters.
        
        Args:
            parameters: Job parameters
                - container: Container name (required)
                - prefix: Optional path prefix filter
                - max_files: Maximum files to analyze
                
        Returns:
            Validated and normalized parameters
            
        Raises:
            ValueError: If required parameters missing or invalid
        """
        # Require container name (support both 'container' and 'container_name')
        container = parameters.get('container') or parameters.get('container_name')
        if not container:
            raise ValueError("Parameter 'container' or 'container_name' is required")
        
        # Validate container name format (Azure naming rules)
        if not (3 <= len(container) <= 63):
            raise ValueError(f"Container name must be 3-63 characters, got {len(container)}")
        
        if not all(c.isalnum() or c == '-' for c in container):
            raise ValueError("Container name can only contain letters, numbers, and hyphens")
        
        # Set defaults
        validated = {
            'container': container.lower(),  # Azure containers are lowercase
            'prefix': parameters.get('prefix', ''),
            'max_files': parameters.get('max_files', ContainerSizeLimits().STANDARD_FILE_COUNT)
        }
        
        logger.info(f"Validated summarize_container parameters: container={validated['container']}, "
                   f"prefix={validated['prefix']}, max_files={validated['max_files']}")
        
        return validated
    
    def create_stage_tasks(self, stage_number: int, job_id: str,
                          job_parameters: Dict[str, Any],
                          previous_stage_results: Optional[Dict[str, Any]] = None) -> List[TaskDefinition]:
        """
        Create tasks for container summarization.
        
        For now, creates a single summary task. Future versions could
        split large containers into parallel analysis chunks.
        
        Args:
            stage_number: Current stage (1 for single-stage)
            job_id: Parent job ID
            job_parameters: Validated job parameters
            previous_stage_results: Not used for single-stage
            
        Returns:
            List with single summary task
        """
        if stage_number != 1:
            logger.warning(f"Unexpected stage number {stage_number} for summarize_container")
            return []
        
        # Create single summary task
        task_id = self.generate_task_id(job_id, stage_number, "summary")
        
        task = TaskDefinition(
            task_id=task_id,
            job_type="summarize_container",
            task_type="summarize_container",
            stage_number=stage_number,
            job_id=job_id,
            parameters={
                'container': job_parameters['container'],
                'prefix': job_parameters.get('prefix', ''),
                'max_files': job_parameters.get('max_files', 2500)
            }
        )
        
        logger.info(f"Created summary task {task_id} for container {job_parameters['container']}")
        return [task]
    
    def aggregate_stage_results(self, stage_number: int,
                                task_results: List[TaskResult]) -> Dict[str, Any]:
        """
        Aggregate results from summary task.
        
        For single-stage workflow, just returns the summary.
        
        Args:
            stage_number: Current stage number
            task_results: Results from completed tasks (TaskResult objects)
            
        Returns:
            Aggregated summary data (JSON-serializable dict)
        """
        if not task_results:
            logger.warning("No task results to aggregate")
            return {"error": "No results available"}
        
        # For single task, extract and return its result_data
        if len(task_results) == 1:
            task = task_results[0]
            # Return the result_data if successful, or error info if failed
            if task.success:
                return task.result_data if task.result_data else {}
            else:
                return {
                    "error": task.error_details or "Task failed",
                    "task_id": task.task_id,
                    "status": "failed"
                }
        
        # Future: aggregate multiple analysis chunks
        # Convert TaskResult objects to dicts for JSON serialization
        serialized_results = []
        for task in task_results:
            serialized_results.append({
                "task_id": task.task_id,
                "status": task.status.value if hasattr(task.status, 'value') else str(task.status),
                "result_data": task.result_data,
                "error_details": task.error_details
            })
        
        return {
            "aggregated_results": serialized_results,
            "task_count": len(task_results)
        }
    
    def should_advance_stage(self, current_stage: int,
                            stage_results: Dict[str, Any]) -> bool:
        """
        Determine if job should advance to next stage.
        
        For single-stage workflow, always returns False.
        
        Args:
            current_stage: Current stage number
            stage_results: Results from current stage
            
        Returns:
            False (single-stage workflow)
        """
        # Single-stage workflow
        return False
    
    def get_job_type(self) -> str:
        """
        Return the job type for this controller.
        
        Returns:
            str: "summarize_container"
        """
        return "summarize_container"
    
    def aggregate_job_results(self, context) -> Dict[str, Any]:
        """
        Aggregate all stage results into final job result.
        
        For single-stage workflow, returns the summary data.
        
        Args:
            context: Job execution context with stage results
            
        Returns:
            Final aggregated job result with container summary
        """
        from datetime import datetime, timezone
        
        # For single-stage, just return the stage 1 results
        if hasattr(context, 'stage_results') and context.stage_results:
            stage_1_results = context.stage_results.get(1, {})
            return {
                'job_type': 'summarize_container',
                'job_id': context.job_id if hasattr(context, 'job_id') else 'unknown',
                'container_summary': stage_1_results,
                'completed_at': datetime.now(timezone.utc).isoformat()
            }
        
        return {
            'job_type': 'summarize_container',
            'job_id': context.job_id if hasattr(context, 'job_id') else 'unknown',
            'error': 'No results available',
            'completed_at': datetime.now(timezone.utc).isoformat()
        }


# ============================================================================
# LIST CONTAINER CONTROLLER
# ============================================================================

@JobRegistry.instance().register(
    job_type="list_container",
    workflow=list_container_workflow,
    description="List container with dynamic task generation for metadata extraction",
    max_parallel_tasks=100,
    timeout_minutes=15
)
class ListContainerController(BaseController):
    """
    Controller for listing container contents with metadata extraction.
    
    Implements the "Analyze & Orchestrate" pattern where Stage 1 analyzes
    the container and dynamically creates Stage 2 tasks based on content.
    
    Workflow:
        Stage 1: Analyze & Orchestrate (single task)
            - Lists all files in container
            - Applies filters
            - Returns orchestration data
            
        Stage 2: Extract Metadata (parallel tasks)
            - One task per file
            - Extracts and stores metadata
            - Results stored in task.result_data
            
        Stage 3: Create Index (optional, single task)
            - Creates filename→task_id mapping
            - Generates summary statistics
    """
    
    def __init__(self):
        """Initialize controller - workflow injected by decorator"""
        super().__init__()
        logger.info("Initialized ListContainerController with dynamic orchestration")
    
    def validate_job_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate container listing parameters.
        
        Args:
            parameters: Job parameters
                - container: Container name (required)
                - filter: Optional search term
                - prefix: Optional path prefix
                - max_files: Maximum files to process
                - metadata_level: Level of extraction (basic/standard/full)
                - create_index: Whether to create Stage 3 index
                
        Returns:
            Validated and normalized parameters
        """
        # Require container name (support both 'container' and 'container_name')
        container = parameters.get('container') or parameters.get('container_name')
        if not container:
            raise ValueError("Parameter 'container' or 'container_name' is required")
        
        # Validate container name
        if not (3 <= len(container) <= 63):
            raise ValueError(f"Container name must be 3-63 characters, got {len(container)}")
        
        # Parse metadata level
        metadata_level = parameters.get('metadata_level', 'standard')
        if metadata_level not in ['basic', 'standard', 'full']:
            metadata_level = 'standard'
        
        # Set defaults
        validated = {
            'container': container.lower(),
            'filter': parameters.get('filter', None),
            'prefix': parameters.get('prefix', ''),
            'max_files': parameters.get('max_files', ContainerSizeLimits().STANDARD_FILE_COUNT),
            'metadata_level': metadata_level,
            'create_index': parameters.get('create_index', False)
        }
        
        logger.info(f"Validated list_container parameters: container={validated['container']}, "
                   f"filter={validated['filter']}, max_files={validated['max_files']}")
        
        return validated
    
    def create_stage_tasks(self, stage_number: int, job_id: str,
                          job_parameters: Dict[str, Any],
                          previous_stage_results: Optional[Dict[str, Any]] = None) -> List[TaskDefinition]:
        """
        Create tasks dynamically based on stage and orchestration data.
        
        Stage 1: Single orchestration task
        Stage 2: Dynamic tasks based on Stage 1 results
        Stage 3: Optional index creation task
        
        Args:
            stage_number: Current stage (1, 2, or 3)
            job_id: Parent job ID
            job_parameters: Validated job parameters
            previous_stage_results: Results from previous stage
            
        Returns:
            List of tasks for the stage
        """
        if stage_number == 1:
            # Stage 1: Single orchestrator task
            task_id = self.generate_task_id(job_id, 1, "orchestrator")
            
            task = TaskDefinition(
                task_id=task_id,
                job_type="list_container",
                task_type="analyze_and_orchestrate",
                stage_number=1,
                job_id=job_id,
                parameters={
                    'container': job_parameters['container'],
                    'filter': job_parameters.get('filter'),
                    'prefix': job_parameters.get('prefix', ''),
                    'max_files': job_parameters.get('max_files', 2500),
                    'metadata_level': job_parameters.get('metadata_level', 'standard')
                }
            )
            
            logger.info(f"Created orchestrator task {task_id}")
            return [task]
        
        elif stage_number == 2:
            # Stage 2: Dynamic tasks based on orchestration
            if not previous_stage_results:
                logger.error("No orchestration data for Stage 2")
                return []
            
            orchestration = previous_stage_results.get('orchestration', {})
            files = orchestration.get('files', [])
            
            if not files:
                logger.warning("No files to process from orchestration")
                return []
            
            logger.info(f"Creating {len(files)} metadata extraction tasks")
            
            tasks = []
            for file_info in files:
                # Create unique task ID based on file path hash
                file_hash = hashlib.md5(file_info['path'].encode()).hexdigest()[:8]
                task_id = self.generate_task_id(job_id, 2, f"file-{file_hash}")
                
                task = TaskDefinition(
                    task_id=task_id,
                    job_type="list_container",
                    task_type="extract_metadata",
                    stage_number=2,
                    job_id=job_id,
                    parameters={
                        'container': job_parameters['container'],
                        'file_path': file_info['path'],
                        'file_size': file_info.get('size', 0),
                        'last_modified': file_info.get('last_modified'),
                        'metadata_level': job_parameters.get('metadata_level', 'standard')
                    }
                )
                tasks.append(task)
            
            logger.info(f"Created {len(tasks)} metadata extraction tasks for Stage 2")
            return tasks
        
        elif stage_number == 3:
            # Stage 3: Optional index creation
            if not job_parameters.get('create_index', False):
                return []
            
            task_id = self.generate_task_id(job_id, 3, "index")
            
            # Count Stage 2 tasks from results
            stage_2_count = len(previous_stage_results.get('task_results', []))
            
            task = TaskDefinition(
                task_id=task_id,
                job_type="list_container",
                task_type="create_file_index",
                stage_number=3,
                job_id=job_id,
                parameters={
                    'container': job_parameters['container'],
                    'job_id': job_id,
                    'stage_2_task_count': stage_2_count
                }
            )
            
            logger.info(f"Created index task {task_id}")
            return [task]
        
        else:
            logger.warning(f"Unexpected stage number {stage_number}")
            return []
    
    def aggregate_stage_results(self, stage_number: int,
                                task_results: List[TaskResult]) -> Dict[str, Any]:
        """
        Aggregate results from completed stage tasks.
        
        Stage 1: Return orchestration data
        Stage 2: Create file→task mapping
        Stage 3: Return index
        
        Args:
            stage_number: Current stage number
            task_results: Results from completed tasks (TaskResult objects)
            
        Returns:
            Aggregated results for the stage (JSON-serializable dict)
        """
        if stage_number == 1:
            # Stage 1: Return orchestration data from single task
            if task_results:
                task = task_results[0]
                if task.success and task.result_data:
                    return task.result_data
                else:
                    return {"error": task.error_details or "Orchestration failed"}
            return {"error": "No orchestration data"}
        
        elif stage_number == 2:
            # Stage 2: Aggregate metadata results
            file_count = len(task_results)
            success_count = sum(1 for task in task_results if task.success)
            
            # Create file→task mapping
            file_index = {}
            for task in task_results:
                if task.success and task.result_data:
                    result = task.result_data
                    if result.get('name'):
                        # Map file name to its metadata
                        file_index[result['name']] = {
                            'size': result.get('size'),
                            'content_type': result.get('content_type'),
                            'last_modified': result.get('last_modified')
                        }
            
            return {
                'stage': 'metadata_extraction',
                'total_files': file_count,
                'successful': success_count,
                'failed': file_count - success_count,
                'file_index': file_index
                # Removed task_results to avoid TaskResult serialization issues
            }
        
        elif stage_number == 3:
            # Stage 3: Return index from single task
            if task_results:
                task = task_results[0]
                if task.success and task.result_data:
                    return task.result_data
                else:
                    return {"error": task.error_details or "Index creation failed"}
            return {"error": "No index data"}
        
        else:
            return {"error": f"Unknown stage {stage_number}"}
    
    def should_advance_stage(self, current_stage: int,
                            stage_results: Dict[str, Any]) -> bool:
        """
        Determine if job should advance to next stage.
        
        Stage 1 → Stage 2: If files were found
        Stage 2 → Stage 3: If create_index is enabled
        
        Args:
            current_stage: Current stage number
            stage_results: Results from current stage
            
        Returns:
            True if should advance, False otherwise
        """
        if current_stage == 1:
            # Advance to Stage 2 if files were found
            orchestration = stage_results.get('orchestration', {})
            files_to_process = orchestration.get('files_to_process', 0)
            should_advance = files_to_process > 0
            
            if should_advance:
                logger.info(f"Advancing to Stage 2 with {files_to_process} files")
            else:
                logger.info("No files to process, completing job")
            
            return should_advance
        
        elif current_stage == 2:
            # Stage 3 is optional, check if index creation requested
            # This would need to be stored in job metadata
            return False  # For now, no Stage 3
        
        else:
            return False
    
    def get_job_type(self) -> str:
        """
        Return the job type for this controller.
        
        Returns:
            str: "list_container"
        """
        return "list_container"
    
    def aggregate_job_results(self, context) -> Dict[str, Any]:
        """
        Aggregate all stage results into final job result.
        
        For list_container, aggregates metadata extraction results.
        
        Args:
            context: Job execution context with stage results
            
        Returns:
            Final aggregated job result with file metadata
        """
        from datetime import datetime, timezone
        
        result = {
            'job_type': 'list_container',
            'job_id': context.job_id if hasattr(context, 'job_id') else 'unknown',
            'completed_at': datetime.now(timezone.utc).isoformat()
        }
        
        if hasattr(context, 'stage_results') and context.stage_results:
            # Stage 1: Orchestration data
            stage_1 = context.stage_results.get(1, {})
            result['orchestration'] = stage_1
            
            # Stage 2: Metadata extraction results
            stage_2 = context.stage_results.get(2, {})
            result['metadata_extraction'] = stage_2
            
            # Calculate summary statistics
            if 'task_count' in stage_2:
                result['summary'] = {
                    'total_files': stage_2.get('task_count', 0),
                    'successful': stage_2.get('successful', 0),
                    'failed': stage_2.get('failed', 0)
                }
        
        return result


# ============================================================================
# REGISTRATION VERIFICATION
# ============================================================================

def verify_registration():
    """
    Verify that controllers are properly registered.
    
    This function is called during module import to ensure
    controllers are available to the JobFactory.
    """
    registry = JobRegistry.instance()
    
    registered_types = [
        "summarize_container",
        "list_container"
    ]
    
    for job_type in registered_types:
        if registry.is_registered(job_type):
            logger.info(f"✅ {job_type} controller registered successfully")
        else:
            logger.error(f"❌ {job_type} controller registration failed")
    
    return all(registry.is_registered(jt) for jt in registered_types)


# Verify registration on import
if __name__ != "__main__":
    verify_registration()