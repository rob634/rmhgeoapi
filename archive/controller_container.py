# ============================================================================
# CLAUDE CONTEXT - CONTROLLER
# ============================================================================
# EPOCH: 3 - DEPRECATED ⚠️
# STATUS: Replaced by Epoch 4 CoreMachine
# MIGRATION: Will be archived after Storage Queue triggers migrated
# PURPOSE: Container operation controllers implementing Job→Stage→Task orchestration for blob storage
# EXPORTS: SummarizeContainerController, ListContainerController (concrete controller implementations)
# INTERFACES: BaseController - implements all abstract methods for workflow orchestration
# PYDANTIC_MODELS: TaskDefinition, WorkflowDefinition, StageResultContract, ContainerOrchestration
# DEPENDENCIES: controller_base, schema_workflow, schema_blob, schema_orchestration, hashlib, typing
# SOURCE: Job parameters from HTTP requests, stage results from task completions via queue messages
# SCOPE: Job-level orchestration for container analysis (summarize) and metadata extraction (list)
# VALIDATION: Parameter validation, container size limits, contract enforcement via @enforce_contract
# PATTERNS: Template Method (BaseController), Dynamic Orchestration (Stage 1 determines Stage 2 tasks)
# ENTRY_POINTS: Registered in function_app.py via job_catalog.register_controller()
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
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

# Contract enforcement imports
from utils import enforce_contract

# Application imports - Core controllers and registry
from controller_base import BaseController
from core.models.results import TaskResult

# Application imports - Schemas
from core.models.workflow import TaskDefinition, StageDefinition, WorkflowDefinition
from schema_blob import ContainerSizeLimits, MetadataLevel
from schema_orchestration import (
    OrchestrationInstruction,
    OrchestrationAction,
    FileOrchestrationItem,
    DynamicOrchestrationResult,
    create_file_orchestration_items
)

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
            timeout_minutes=10
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

class SummarizeContainerController(BaseController):
    """
    Static registration metadata for explicit registration.

    This metadata will be used by JobCatalog for explicit registration,
    allowing us to move away from decorator-based import-time registration.
    """
    REGISTRATION_INFO = {
        'job_type': 'summarize_container',
        'workflow': summarize_container_workflow,
        'description': 'Generate container statistics and summary',
        'max_parallel_tasks': 1,
        'timeout_minutes': 10,
        'stages': {
            'summarize': {
                'stage_number': 1,
                'task_type': 'summarize_container',
                'max_parallel': 1
            }
        },
        'required_env_vars': [
            'AZURE_STORAGE_ACCOUNT_URL',
            'BRONZE_CONTAINER',
            'SILVER_CONTAINER'
        ],
        'dependencies': ['azure-storage-blob', 'azure-identity']
    }
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
    
    @enforce_contract(
        params={'parameters': dict},
        returns=dict
    )
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
        # Map tier names to actual container names from config
        from config import get_config
        config = get_config()

        container_map = {
            'bronze': config.bronze_container_name,
            'silver': config.silver_container_name,
            'gold': config.gold_container_name
        }

        # Get container parameter and map to full name if needed
        container_param = parameters.get('container', 'bronze')  # Default to bronze
        container = container_map.get(container_param.lower(), container_param)

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
    
    @enforce_contract(
        params={
            'stage_number': int,
            'job_id': str,
            'job_parameters': dict,
            'previous_stage_results': (dict, type(None))
        },
        returns=list
    )
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
            logger.error(f"Invalid stage number {stage_number} for summarize_container")
            raise ValueError(f"Invalid stage number {stage_number} for summarize_container")
        
        # Create single summary task
        try:
            task_id = self.generate_task_id(job_id, stage_number, "summary")
            logger.info(f"Creating summary task {task_id} for container {job_parameters['container']}")
            task = TaskDefinition(
                task_id=task_id,
                job_type="summarize_container",
                task_type="summarize_container",
                stage_number=stage_number,
                job_id=job_id,
                parameters={
                    'container': job_parameters['container'],
                    'prefix': job_parameters.get('prefix', ''),
                    'max_files': job_parameters.get('max_files', 2500),
                    'task_index': 'summary'  # Add unique task_index for summary task
                }
            )
        except Exception as e:
            logger.error(f"Error creating summarize_container task: {e}")
            raise
        
        logger.info(f"Created summary task {task_id} for container {job_parameters['container']}")
        return [task]
    
    def aggregate_stage_results(self, stage_number: int,
                                task_results: List[TaskResult]) -> Dict[str, Any]:
        """
        Aggregate results from summary task.

        MUST return StageResultContract-compliant format for proper stage advancement.

        Args:
            stage_number: Current stage number
            task_results: Results from completed tasks (TaskResult objects)

        Returns:
            Dict matching StageResultContract schema
        """
        if not task_results or len(task_results) == 0:
            logger.error("❌ No task results to aggregate for summary")
            raise ValueError("Cannot aggregate summary without task results")

        # Count successes and failures
        successful = [t for t in task_results if t.success]
        failed = [t for t in task_results if not t.success]

        # Calculate success rate
        success_rate = (len(successful) / len(task_results) * 100) if task_results else 0.0

        # Determine overall status
        if len(failed) == 0:
            status = 'completed'
        elif len(successful) == 0:
            status = 'failed'
        else:
            status = 'completed_with_errors'

        # Extract container summary data for metadata
        metadata = {}
        if len(task_results) == 1:
            task = task_results[0]
            if task.success and task.result_data:
                # Put the actual summary data in metadata
                metadata['container_summary'] = task.result_data
                metadata['stage_name'] = 'summarize'
            elif not task.success:
                metadata['error'] = task.error_details or "Task failed without error details"
        
        # Return StageResultContract-compliant format
        return {
            'stage_number': stage_number,
            'stage_key': str(stage_number),
            'status': status,
            'task_count': len(task_results),
            'successful_tasks': len(successful),
            'failed_tasks': len(failed),
            'success_rate': success_rate,
            'task_results': [t.model_dump(mode='json') if hasattr(t, 'model_dump') else t for t in task_results],
            'completed_at': datetime.now(timezone.utc).isoformat(),
            'metadata': metadata
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
        # Single-stage workflow - parameters required by base class but not used
        _ = (current_stage, stage_results)  # Suppress unused warnings
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
        
        # For single-stage, just return the stage 1 results
        if hasattr(context, 'stage_results') and context.stage_results:
            # CONTRACT: stage_results keys are always strings
            stage_1_results = context.stage_results.get('1', {})
            if hasattr(context, 'job_id'):
                logger.info(f"Aggregating job results for job_id: {context.job_id}")
            else:
                logger.critical("Context missing job_id attribute")
                return {
                    'job_type': 'summarize_container',
                    'job_id': None,
                    'error': 'Context missing job_id attribute',
                    'completed_at': datetime.now(timezone.utc).isoformat()
                }
            if context.job_id:
                logger.info(f"Aggregated job results for job_id: {context.job_id}")
                return {
                    'job_type': 'summarize_container',
                    'job_id': context.job_id,
                    'container_summary': stage_1_results,
                    'completed_at': datetime.now(timezone.utc).isoformat()
                }
            else:
                logger.error("Context job_id is None or empty")
                return {
                    'job_type': 'summarize_container',
                    'job_id': None,
                    'error': 'Context job_id is None or empty',
                    'completed_at': datetime.now(timezone.utc).isoformat()
                }

        else:
            logger.error(f"No stage results available in context")
            return {
                'job_type': 'summarize_container',
                'job_id': context.job_id if hasattr(context, 'job_id') else 'unknown',
                'error': 'No results available',
                'completed_at': datetime.now(timezone.utc).isoformat()
            }


# ============================================================================
# LIST CONTAINER CONTROLLER
# ============================================================================

class ListContainerController(BaseController):
    """
    Static registration metadata for explicit registration.

    This metadata will be used by JobCatalog for explicit registration.
    Demonstrates dynamic orchestration with analyze & orchestrate pattern.
    """
    REGISTRATION_INFO = {
        'job_type': 'list_container',
        'workflow': list_container_workflow,
        'description': 'List container with dynamic task generation for metadata extraction',
        'max_parallel_tasks': 100,
        'timeout_minutes': 20,
        'stages': {
            'analyze_orchestrate': {
                'stage_number': 1,
                'task_type': 'analyze_and_orchestrate',
                'max_parallel': 1,
                'description': 'Analyze container and create dynamic tasks'
            },
            'extract_metadata': {
                'stage_number': 2,
                'task_type': 'extract_metadata',
                'max_parallel': 100,
                'depends_on': 'analyze_orchestrate',
                'description': 'Extract metadata from files (dynamically generated)'
            }
        },
        'required_env_vars': [
            'AZURE_STORAGE_ACCOUNT_URL',
            'BRONZE_CONTAINER',
            'SILVER_CONTAINER'
        ],
        'dependencies': ['azure-storage-blob', 'azure-identity'],
        'features': ['dynamic_orchestration', 'metadata_extraction']
    }

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

    def supports_dynamic_orchestration(self) -> bool:
        """Enable dynamic orchestration for this controller."""
        return True

    @enforce_contract(
        params={'parameters': dict},
        returns=dict
    )
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
        # Map tier names to actual container names from config
        from config import get_config
        config = get_config()

        container_map = {
            'bronze': config.bronze_container_name,
            'silver': config.silver_container_name,
            'gold': config.gold_container_name
        }

        # Get container parameter and map to full name if needed
        container_param = parameters.get('container', 'bronze')  # Default to bronze
        container = container_map.get(container_param.lower(), container_param)

        # Validate container name
        if not (3 <= len(container) <= 63):
            raise ValueError(f"Container name must be 3-63 characters, got {len(container)}")
        
        # Parse metadata level (optional with default)
        metadata_level = parameters.get('metadata_level', 'standard')
        if not metadata_level:
            logger.warning("metadata_level not provided, using 'standard'")
            metadata_level = 'standard'
        if metadata_level not in ['basic', 'standard', 'full']:
            raise ValueError(f"metadata_level must be 'basic', 'standard', or 'full' recieved :{metadata_level}")
            #metadata_level = 'standard'

        logger.info(f"Metadata level: {metadata_level}")
        
        # Set defaults
        try:
            validated = {
                'container': container.lower(),
                'filter': parameters.get('filter', None),
                'prefix': parameters.get('prefix', ''),
                'max_files': parameters.get('max_files', ContainerSizeLimits().STANDARD_FILE_COUNT),
                'metadata_level': metadata_level,
                'create_index': parameters.get('create_index', False)
            }
        except Exception as e:
            logger.error(f"Error validating job parameters: {e}")
            raise
        
        logger.info(f"Validated list_container parameters: container={validated['container']}, "f"filter={validated['filter']}, max_files={validated['max_files']}")

        return validated

    @enforce_contract(
        params={
            'stage_number': int,
            'job_id': str,
            'job_parameters': dict,
            'previous_stage_results': (dict, type(None))
        },
        returns=list
    )
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
            logger.debug(f"🎯 Stage 1: Creating orchestrator task")
            task_id = self.generate_task_id(job_id, 1, "orchestrator")
            logger.debug(f"  Generated task_id: {task_id}")
            try:
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
                        'metadata_level': job_parameters.get('metadata_level', 'standard'),
                        'task_index': 'orchestrator'  # Add unique task_index for Stage 1
                    }
                )
            except Exception as e:
                logger.error(f"❌ Error creating list_container Stage 1 task: {e}")
                raise
            
            logger.info(f"Created orchestrator task {task_id}")
            return [task]
        
        elif stage_number == 2:
            # Stage 2: Dynamic tasks based on orchestration
            logger.debug(f"🎯 Stage 2: Starting dynamic task creation")

            if not previous_stage_results:
                logger.error("❌ No previous_stage_results for Stage 2")
                raise ValueError(f"❌ Previous stage results are required for Stage 2")

            logger.debug(f"📋 Previous stage result keys: {list(previous_stage_results.keys())}")

            # Parse orchestration instruction using base class method
            try:
                orchestration = self.parse_orchestration_instruction(previous_stage_results)
            except Exception as e:
                logger.error(f"❌ Error parsing orchestration instruction: {e}")
                raise
            if not orchestration:
                logger.error("❌ None orchestration instruction parsed")
                raise ValueError("❌ None orchestration instruction parsed")

            logger.info(f"✅ Parsed orchestration: action={orchestration.action}, items={len(orchestration.items)}")

            # Check if we should create tasks
            if orchestration.should_create_tasks():
                logger.info(f"🏗️ Creating {len(orchestration.items)} metadata extraction tasks")
            else:
                logger.warning(f"⏭️ Orchestration action is {orchestration.action}, not creating tasks")
                return []

            # Use the formal orchestration items
            tasks = []
            for idx, item in enumerate(orchestration.items):
                # FileOrchestrationItem guarantees both item_id (hash) and path fields
                # item_id is the deterministic hash, path is the actual file location
                logger.debug(f"  📄 Processing item {idx}: type={item.item_type}, id={item.item_id}")
                logger.debug(f"    Path: {item.path[:50]}..." if len(item.path) > 50 else f"    Path: {item.path}")

                # Create unique task ID using the item_id (deterministic hash)
                try:
                    # Use first 8 chars of the hash for task ID suffix
                    task_suffix = f"item-{item.item_id[:8]}"
                    task_id = self.generate_task_id(job_id, 2, task_suffix)
                    logger.debug(f"    Generated task_id: {task_id}")
                except Exception as e:
                    logger.error(f"❌ Error generating task ID for file {item.path}: {e}")
                    raise
                
                try:
                    logger.debug(f"Creating task definition for {task_id}")
                    task = TaskDefinition(
                        task_id=task_id,
                        job_type="list_container",
                        task_type="extract_metadata",
                        stage_number=2,
                        job_id=job_id,
                        parameters={
                            'container': item.container,  # Use container from FileOrchestrationItem
                            'file_path': item.path,       # Use path from FileOrchestrationItem
                            'file_size': item.size if item.size else 0,
                            'last_modified': item.last_modified.isoformat() if item.last_modified else None,
                            'metadata_level': job_parameters.get('metadata_level', 'standard'),
                            'task_index': f"item-{idx:04d}-{item.item_id[:8]}",
                            # Include any additional stage 2 parameters from orchestration
                            **orchestration.stage_2_parameters
                        }
                    )
                    logger.debug(f"    Created task definition for {task_id}")
                except Exception as e:
                    logger.error(f"❌ Error creating task definition for file {item.path}: {e}")
                    raise

                tasks.append(task)

            logger.info(f"Created {len(tasks)} metadata extraction tasks for Stage 2")
            return tasks
        
        elif stage_number == 3:
            # Stage 3: Optional index creation
            build_index = job_parameters.get('create_index', False)

            if build_index:
                logger.debug(f"Building index for {job_id}")
            else:
                logger.error(f"Stage 3 specified without index parameters")
                raise ValueError("Stage 3 specified without index parameters")

            try:
                task_id = self.generate_task_id(job_id, 3, "index")
            except Exception as e:
                logger.error(f"❌ Error generating task ID for Stage 3 index: {e}")
                raise
        
            # Validate previous stage results exist for Stage 3
            if not previous_stage_results:
                logger.error("❌ No previous stage results for Stage 3 index creation")
                raise ValueError("Stage 3 requires Stage 2 results")

            # Count Stage 2 tasks from results
            try:
                stage_2_count = len(previous_stage_results.get('task_results', []))
                if stage_2_count == 0:
                    logger.warning("⚠️ Stage 3 creating index for 0 files")
                
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
            except Exception as e:
                logger.error(f"❌ Error creating Stage 3 index task definition: {e}")
                raise
                
            logger.info(f"Created index task {task_id}")
            return [task]
        
        else:
            error_message = f"Invalid stage number {stage_number} for list_container"
            logger.error(error_message)
            raise RuntimeError(error_message)

    @enforce_contract(
        params={
            'stage_number': int,
            'task_results': list
        },
        returns=dict
    )
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
            # Stage 1: Return orchestration data in formal format
            logger.debug(f"🎯 Stage 1 aggregate_stage_results: Processing {len(task_results)} task results")

            if task_results:
                task = task_results[0]
                logger.debug(f"  Task success: {task.success}, Has result_data: {task.result_data is not None}")

                if task.success and task.result_data:
                    # The service should return data with 'orchestration' key containing files
                    raw_data = task.result_data
                    logger.debug(f"  Raw data keys: {list(raw_data.keys())}")

                    # Check if service already returns formal orchestration
                    if 'orchestration' in raw_data and 'action' in raw_data.get('orchestration', {}):
                        # Already in formal format but needs contract compliance
                        logger.debug("  ✅ Data already in formal orchestration format, wrapping in contract")
                        # Count successes and failures
                        successful = [t for t in task_results if t.success]
                        failed = [t for t in task_results if not t.success]

                        # Return StageResultContract-compliant format
                        return {
                            'stage_number': stage_number,
                            'stage_key': str(stage_number),
                            'status': 'completed' if len(failed) == 0 else 'completed_with_errors',
                            'task_count': len(task_results),
                            'successful_tasks': len(successful),
                            'failed_tasks': len(failed),
                            'success_rate': (len(successful) / len(task_results) * 100) if task_results else 0.0,
                            'task_results': [t.model_dump(mode='json') if hasattr(t, 'model_dump') else t for t in task_results],
                            'completed_at': datetime.now(timezone.utc).isoformat(),
                            'metadata': {
                                'stage_name': 'analyze_orchestrate',
                                **raw_data  # Include all orchestration data in metadata
                            }
                        }

                    logger.debug("  📦 Converting to formal orchestration format")

                    # Convert to formal orchestration format
                    orchestration_data = raw_data.get('orchestration', {})
                    logger.debug(f"  Orchestration data keys: {list(orchestration_data.keys()) if orchestration_data else 'None'}")

                    files = orchestration_data.get('files', [])
                    logger.debug(f"  Found {len(files)} files to orchestrate")

                    # Create formal orchestration items
                    # Get container from orchestration data or task metadata
                    container = orchestration_data.get('container', 'unknown')
                    logger.debug(f"  Container: {container}")

                    logger.debug(f"  Creating FileOrchestrationItems from {len(files)} files")
                    orchestration_items = create_file_orchestration_items(
                        files=files,
                        container=container
                    )
                    logger.debug(f"  Created {len(orchestration_items)} orchestration items")

                    # Determine action based on files found
                    # Even with 0 files, we still complete normally but with a warning
                    if files:
                        action = OrchestrationAction.CREATE_TASKS
                        reason = None
                        warnings = orchestration_data.get('warnings', [])
                    else:
                        # Don't create tasks, but complete normally with warning
                        action = OrchestrationAction.COMPLETE_JOB
                        reason = f"No files found matching filter criteria (filter={orchestration_data.get('filter', 'none')})"
                        warnings = orchestration_data.get('warnings', [])
                        warnings.append(f"No files matched the filter '{orchestration_data.get('filter', 'none')}' - job completing with 0 files processed")
                    logger.debug(f"  Orchestration action: {action}")

                    # Create formal orchestration instruction
                    instruction = OrchestrationInstruction(
                        action=action,
                        items=orchestration_items,
                        total_items=orchestration_data.get('total_files', len(files)),
                        items_filtered=orchestration_data.get('files_filtered', 0),
                        items_included=len(files),
                        reason=reason,  # Add reason for COMPLETE_JOB action
                        stage_2_parameters={
                            'metadata_level': orchestration_data.get('metadata_level', 'standard')
                        },
                        orchestration_metadata=orchestration_data.get('summary', {})
                    )
                    logger.debug(f"  Created OrchestrationInstruction with {len(instruction.items)} items")

                    # Return as DynamicOrchestrationResult
                    result = DynamicOrchestrationResult(
                        orchestration=instruction,
                        analysis_summary=orchestration_data.get('summary', {}),
                        statistics={
                            'total_files': orchestration_data.get('total_files', 0),
                            'files_included': len(files),
                            'files_filtered': orchestration_data.get('files_filtered', 0)
                        },
                        discovered_metadata=orchestration_data.get('metadata', {}),
                        warnings=warnings  # Use the warnings list we updated above
                    )
                    logger.debug(f"  Created DynamicOrchestrationResult")

                    stage_result = result.to_stage_result()
                    logger.debug(f"  Stage result keys: {list(stage_result.keys())}")
                    logger.info(f"✅ Stage 1 returning orchestration for {len(files)} files")

                    # Count successes and failures
                    successful = [t for t in task_results if t.success]
                    failed = [t for t in task_results if not t.success]
                    warnings_list = stage_result.get('warnings', [])

                    # Determine status based on failures and warnings
                    if len(failed) > 0:
                        status = 'completed_with_errors'
                    elif warnings_list:
                        status = 'completed_with_warnings'
                    else:
                        status = 'completed'

                    # Return StageResultContract-compliant format
                    return {
                        'stage_number': stage_number,
                        'stage_key': str(stage_number),
                        'status': status,
                        'task_count': len(task_results),
                        'successful_tasks': len(successful),
                        'failed_tasks': len(failed),
                        'success_rate': (len(successful) / len(task_results) * 100) if task_results else 0.0,
                        'task_results': [t.model_dump(mode='json') if hasattr(t, 'model_dump') else t for t in task_results],
                        'completed_at': datetime.now(timezone.utc).isoformat(),
                        'metadata': {
                            'stage_name': 'analyze_orchestrate',
                            'orchestration': stage_result.get('orchestration', {}),
                            'statistics': stage_result.get('statistics', {}),
                            'analysis_summary': stage_result.get('analysis_summary', {}),
                            'discovered_metadata': stage_result.get('discovered_metadata', {}),
                            'warnings': warnings_list
                        }
                    }
                else:
                    error_msg = task.error_details or "Orchestration failed"
                    logger.error(f"❌ Stage 1 orchestration failed: {error_msg}")
                    raise RuntimeError(f"Stage 1 orchestration failed: {error_msg}")

            logger.error("❌ No orchestration data available from Stage 1")
            raise ValueError("Stage 1 failed to produce orchestration data")
        
        elif stage_number == 2:
            # Stage 2: Aggregate metadata results
            if not task_results:
                logger.error("❌ No task results for Stage 2 aggregation")
                raise ValueError("Stage 2 has no task results to aggregate")

            file_count = len(task_results)
            success_count = sum(1 for task in task_results if task.success)

            # Check if too many failures
            failure_rate = (file_count - success_count) / file_count if file_count > 0 else 0
            if failure_rate > 0.5:  # More than 50% failed
                logger.error(f"❌ High failure rate in Stage 2: {failure_rate:.1%} ({file_count - success_count}/{file_count} failed)")
                # Log but don't fail - let the job complete with partial results
            
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

            # Determine overall status
            if file_count - success_count == 0:
                status = 'completed'
            elif success_count == 0:
                status = 'failed'
            else:
                status = 'completed_with_errors'

            # Return StageResultContract-compliant format
            return {
                'stage_number': stage_number,
                'stage_key': str(stage_number),
                'status': status,
                'task_count': file_count,
                'successful_tasks': success_count,
                'failed_tasks': file_count - success_count,
                'success_rate': (success_count / file_count * 100) if file_count > 0 else 0.0,
                'task_results': [t.model_dump(mode='json') if hasattr(t, 'model_dump') else t for t in task_results],
                'completed_at': datetime.now(timezone.utc).isoformat(),
                'metadata': {
                    'stage_name': 'metadata_extraction',
                    'file_index': file_index,
                    'total_files_processed': file_count
                }
            }
        
        elif stage_number == 3:
            # Stage 3: Return index from single task
            if not task_results:
                logger.error("❌ No task results for Stage 3 index aggregation")
                raise ValueError("Stage 3 has no index task result")

            if task_results:
                task = task_results[0]

                # Count successes and failures
                successful = [t for t in task_results if t.success]
                failed = [t for t in task_results if not t.success]

                # Prepare metadata
                metadata = {'stage_name': 'create_index'}
                if task.success and task.result_data:
                    metadata['index_data'] = task.result_data
                else:
                    metadata['error'] = task.error_details or "Index creation failed"

                # Return StageResultContract-compliant format
                return {
                    'stage_number': stage_number,
                    'stage_key': str(stage_number),
                    'status': 'completed' if len(failed) == 0 else 'failed',
                    'task_count': len(task_results),
                    'successful_tasks': len(successful),
                    'failed_tasks': len(failed),
                    'success_rate': (len(successful) / len(task_results) * 100) if task_results else 0.0,
                    'task_results': [t.model_dump(mode='json') if hasattr(t, 'model_dump') else t for t in task_results],
                    'completed_at': datetime.now(timezone.utc).isoformat(),
                    'metadata': metadata
                }

            logger.error("❌ No index data available from Stage 3")
            raise ValueError("Stage 3 failed to produce index data")
        
        else:
            logger.error(f"❌ Unknown stage number {stage_number} for aggregation")
            raise ValueError(f"Invalid stage number {stage_number} for list_container aggregation")

    @enforce_contract(
        params={
            'current_stage': int,
            'stage_results': dict
        },
        returns=bool
    )
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
            # Validate stage_results exists
            if not stage_results:
                logger.error("❌ No stage results available for advancement decision")
                raise ValueError("Cannot determine stage advancement without stage results")

            # Check metadata for orchestration details
            metadata = stage_results.get('metadata', {})
            orchestration_data = metadata.get('orchestration', {})

            # Check the orchestration action
            action = orchestration_data.get('action')
            if action == 'complete_job':
                completion_reason = orchestration_data.get('reason', 'No items to process')
                warnings = metadata.get('warnings', [])
                if warnings:
                    logger.info(f"Job completing with warnings: {warnings[0]}")
                else:
                    logger.info(f"Job completing: {completion_reason}")
                return False

            # Check if there are items to process
            items = orchestration_data.get('items', [])
            if items:
                logger.info(f"Advancing to Stage 2 with {len(items)} items to process")
                return True

            # Legacy check for backward compatibility
            files_to_process = orchestration_data.get('files_to_process', 0)
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
            # CONTRACT: stage_results keys are always strings
            stage_1 = context.stage_results.get('1', {})
            result['orchestration'] = stage_1

            # Stage 2: Metadata extraction results
            stage_2 = context.stage_results.get('2', {})
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

# Registration verification removed - now handled by explicit registration
# Controllers are registered via REGISTRATION_INFO metadata in function_app.py