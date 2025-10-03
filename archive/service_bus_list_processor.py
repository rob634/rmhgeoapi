# ============================================================================
# CLAUDE CONTEXT - CONTROLLER
# ============================================================================
# EPOCH: SHARED - BOTH EPOCHS
# STATUS: Used by Epoch 3 and Epoch 4
# NOTE: Careful migration required
# PURPOSE: Reusable base class for "list-then-process" workflows optimized for Service Bus
# EXPORTS: ServiceBusListProcessor - base for analyze/list → batch process patterns
# INTERFACES: Extends CoreController with list-then-process pattern
# PYDANTIC_MODELS: TaskDefinition, OrchestrationInstruction, various item types
# DEPENDENCIES: controller_core, state_manager, orchestration_manager
# SOURCE: Common pattern extracted from container operations
# SCOPE: All workflows that analyze then batch process items
# VALIDATION: Enforces two-stage pattern with orchestration
# PATTERNS: Template Method for list-then-process workflows
# ENTRY_POINTS: Inherited by specific list-then-process controllers
# INDEX: ServiceBusListProcessor:100, analyze_source:300, process_item:400
# ============================================================================

"""
Service Bus List Processor - Reusable List-Then-Process Pattern

Base class for the extremely common pattern:
- Stage 1: List/analyze source → return items
- Stage 2: Process each item in batches

Examples:
- List container → extract metadata for each file
- List container → create STAC item for each file
- Read GeoJSON → split and process each feature batch
- Query database → process each record
- Read CSV → process each row batch

This base class handles all the orchestration boilerplate, leaving
concrete controllers to just implement:
1. How to analyze the source
2. How to process each item

Author: Robert and Geospatial Claude Legion
Date: 26 SEP 2025
"""

from abc import abstractmethod
from typing import Dict, Any, List, Optional, Union
from datetime import datetime

# Base classes
from core import CoreController, StateManager, OrchestrationManager

# Pydantic models - using new core.models structure
from core.models import TaskDefinition
from schema_orchestration import (
    OrchestrationInstruction,
    OrchestrationAction,
    OrchestrationItem,
    FileOrchestrationItem
)

# Logging
from util_logger import LoggerFactory, ComponentType


class ServiceBusListProcessor(CoreController):
    """
    Base class for list-then-process workflows with Service Bus optimization.

    Implements the common pattern:
    - Stage 1: Single task to analyze/list source
    - Stage 2: Batch process items found in Stage 1

    Concrete controllers only need to implement:
    - analyze_source(): How to list/analyze in Stage 1
    - process_item(): How to process each item in Stage 2
    - get_job_type(): Job type identifier

    Everything else (orchestration, batching, state management) is handled!

    Usage:
        class MyListProcessor(ServiceBusListProcessor):
            def get_job_type(self):
                return "my_list_processor"

            def analyze_source(self, params):
                items = fetch_items_from_source(params)
                return self.create_orchestration_items(items)

            def get_stage_2_task_type(self):
                return "process_my_item"
    """

    # Override these in subclasses
    DEFAULT_BATCH_SIZE = 100  # Align with Service Bus
    DEFAULT_BATCH_THRESHOLD = 50  # Use batching if >= 50 items

    def __init__(self):
        """Initialize with state manager and orchestration manager."""
        super().__init__()
        self.state_manager = StateManager()
        self.orchestrator = OrchestrationManager(self.get_job_type())
        self.batch_metrics = []

    # ========================================================================
    # JOB RECORD MANAGEMENT (Required for job submission)
    # ========================================================================

    def create_job_record(self, job_id: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create and store the initial job record.

        This is required for job submission compatibility with the current
        trigger system. Should eventually be moved to trigger layer.
        """
        from core.models import JobRecord, JobStatus
        from datetime import datetime, timezone

        # Create JobRecord instance
        job_record = JobRecord(
            job_id=job_id,
            job_type=self.get_job_type(),
            status=JobStatus.QUEUED,
            stage=1,
            parameters=parameters,
            metadata={
                'processing_path': 'service_bus',
                'architecture': 'clean'
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

        # Store in database via StateManager
        self.state_manager.create_job_record(job_record)

        return job_record

    # ========================================================================
    # TEMPLATE METHOD - Defines the list-then-process pattern
    # ========================================================================

    def create_stage_tasks(
        self,
        stage_number: int,
        job_id: str,
        job_parameters: Dict[str, Any],
        previous_stage_results: Optional[List[Dict[str, Any]]] = None
    ) -> List[TaskDefinition]:
        """
        Create tasks for each stage of the list-then-process workflow.

        Stage 1: Single analysis task
        Stage 2: Batch tasks from orchestration

        Args:
            stage_number: 1 or 2
            job_id: Parent job ID
            job_parameters: Validated job parameters
            previous_stage_results: Results from Stage 1 (for Stage 2)

        Returns:
            List of tasks to execute
        """
        # CONTRACT ENFORCEMENT - Validate parameters
        from exceptions import ContractViolationError

        if not isinstance(stage_number, int):
            raise ContractViolationError(
                f"Contract violation in {self.__class__.__name__}.create_stage_tasks: "
                f"stage_number must be int, got {type(stage_number).__name__}"
            )

        if not isinstance(job_id, str):
            raise ContractViolationError(
                f"Contract violation in {self.__class__.__name__}.create_stage_tasks: "
                f"job_id must be str, got {type(job_id).__name__}"
            )

        if not isinstance(job_parameters, dict):
            raise ContractViolationError(
                f"Contract violation in {self.__class__.__name__}.create_stage_tasks: "
                f"job_parameters must be dict, got {type(job_parameters).__name__}"
            )

        if previous_stage_results is not None and not isinstance(previous_stage_results, list):
            raise ContractViolationError(
                f"Contract violation in {self.__class__.__name__}.create_stage_tasks: "
                f"previous_stage_results must be list or None, got {type(previous_stage_results).__name__}"
            )

        if stage_number == 1:
            # Stage 1: Single task to analyze source
            tasks = self._create_stage_1_tasks(job_id, job_parameters)
        elif stage_number == 2:
            # Stage 2: Process items from Stage 1
            if not previous_stage_results:
                self.logger.warning("No previous results for Stage 2")
                return []

            tasks = self._create_stage_2_tasks(
                job_id, job_parameters, previous_stage_results
            )
        else:
            self.logger.error(f"Invalid stage number: {stage_number}")
            return []

        # CONTRACT ENFORCEMENT - Validate returned tasks
        if not isinstance(tasks, list):
            raise ContractViolationError(
                f"Contract violation: {self.__class__.__name__}._create_stage_*_tasks must return list, "
                f"got {type(tasks).__name__}"
            )

        for idx, task in enumerate(tasks):
            if not isinstance(task, TaskDefinition):
                raise ContractViolationError(
                    f"Contract violation: Task at index {idx} must be TaskDefinition, "
                    f"got {type(task).__name__}"
                )

        return tasks

    def _create_stage_1_tasks(
        self,
        job_id: str,
        parameters: Dict[str, Any]
    ) -> List[TaskDefinition]:
        """
        Create Stage 1 analysis task.

        Single task that will analyze/list the source.
        """
        task = TaskDefinition(
            task_id=f"{job_id[:8]}-s1-analyze",
            job_id=job_id,
            job_type=self.get_job_type(),
            task_type=self.get_stage_1_task_type(),
            stage_number=1,
            parameters=parameters
        )

        self.logger.info(f"Created Stage 1 analysis task: {task.task_id}")
        return [task]

    def _create_stage_2_tasks(
        self,
        job_id: str,
        parameters: Dict[str, Any],
        previous_results: List[Dict[str, Any]]
    ) -> List[TaskDefinition]:
        """
        Create Stage 2 processing tasks from orchestration.

        Parses orchestration from Stage 1 and creates batch tasks.
        """
        if not previous_results:
            self.logger.warning("No Stage 1 results to process")
            return []

        # Parse orchestration from Stage 1
        stage_1_result = previous_results[0] if previous_results else {}
        instruction = self.orchestrator.parse_stage_results(stage_1_result)

        if not instruction:
            self.logger.warning("No orchestration instruction from Stage 1")
            return []

        if instruction.action == OrchestrationAction.COMPLETE_JOB:
            self.logger.info("Stage 1 indicated job completion, no Stage 2 tasks")
            return []

        # Create tasks from orchestration
        if self._should_use_batching(len(instruction.items)):
            # Create aligned batches for Service Bus
            batches = self.orchestrator.create_batch_tasks(
                instruction, job_id, 2, parameters
            )
            # Flatten batches (Service Bus will re-batch during queueing)
            all_tasks = [task for batch in batches for task in batch]

            self.logger.info(
                f"Created {len(all_tasks)} tasks in {len(batches)} batches"
            )
            return all_tasks
        else:
            # Create tasks individually for small sets
            tasks = self.orchestrator.create_tasks_from_instruction(
                instruction, job_id, 2, parameters
            )
            self.logger.info(f"Created {len(tasks)} individual tasks")
            return tasks

    # ========================================================================
    # ABSTRACT METHODS - Must be implemented by concrete controllers
    # ========================================================================

    @abstractmethod
    def analyze_source(
        self,
        parameters: Dict[str, Any]
    ) -> Union[List[OrchestrationItem], OrchestrationInstruction]:
        """
        Analyze/list the source in Stage 1.

        This is where you:
        - List container files
        - Read GeoJSON features
        - Query database records
        - Parse CSV rows

        Args:
            parameters: Job parameters

        Returns:
            Either:
            - List of OrchestrationItems (will be wrapped in instruction)
            - Complete OrchestrationInstruction (for custom control)

        Example:
            def analyze_source(self, params):
                files = list_container(params['container'])
                return [FileOrchestrationItem(
                    container=params['container'],
                    path=f['name'],
                    size=f['size']
                ) for f in files]
        """
        pass

    def get_stage_1_task_type(self) -> str:
        """
        Get task type for Stage 1 analysis.

        Override to customize. Default: "analyze_{job_type}"
        """
        return f"analyze_{self.get_job_type()}"

    def get_stage_2_task_type(self) -> str:
        """
        Get task type for Stage 2 processing.

        Override to customize. Default: "process_{job_type}_item"
        """
        return f"process_{self.get_job_type()}_item"

    # ========================================================================
    # STAGE 1 EXECUTION - Called by task processor
    # ========================================================================

    def execute_stage_1(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute Stage 1 analysis and return orchestration.

        This method is called by the task processor for Stage 1 tasks.
        It calls analyze_source() and wraps the result in proper format.

        Args:
            parameters: Task parameters

        Returns:
            Task result with orchestration in metadata
        """
        # CONTRACT ENFORCEMENT - Validate input
        from exceptions import ContractViolationError, BusinessLogicError

        if not isinstance(parameters, dict):
            raise ContractViolationError(
                f"Contract violation in ServiceBusListProcessor.execute_stage_1: "
                f"parameters must be dict, got {type(parameters).__name__}"
            )

        self.logger.info("Executing Stage 1 analysis")

        try:
            # Call abstract method to analyze source
            result = self.analyze_source(parameters)

            # CONTRACT ENFORCEMENT - Validate return type from analyze_source
            if not isinstance(result, (list, OrchestrationInstruction)):
                raise ContractViolationError(
                    f"Contract violation: analyze_source() must return list or OrchestrationInstruction, "
                    f"got {type(result).__name__} from {self.__class__.__name__}"
                )

            # Convert result to OrchestrationInstruction if needed
            if isinstance(result, OrchestrationInstruction):
                instruction = result
            elif isinstance(result, list):
                # CONTRACT ENFORCEMENT - List items must be OrchestrationItems
                for idx, item in enumerate(result):
                    if not isinstance(item, OrchestrationItem):
                        raise ContractViolationError(
                            f"Contract violation: analyze_source() returned list with invalid item at index {idx}. "
                            f"Expected OrchestrationItem, got {type(item).__name__}"
                        )

                # Wrap items in instruction
                instruction = self.orchestrator.create_instruction(
                    items=result,
                    action=OrchestrationAction.CREATE_TASKS,
                    stage_2_parameters={
                        'task_type': self.get_stage_2_task_type()
                    }
                )
            else:
                # This should never happen due to earlier check, but being defensive
                raise ContractViolationError(f"Invalid analyze_source result type: {type(result)}")

            # Return with orchestration in metadata (StageResultContract pattern)
            return {
                'success': True,
                'items_found': len(instruction.items),
                'action': instruction.action.value,
                'metadata': {
                    'orchestration': instruction.model_dump(mode='json')
                }
            }

        except ContractViolationError:
            # Contract violations should bubble up - they indicate bugs
            raise

        except BusinessLogicError as e:
            # Expected business failure (e.g., container doesn't exist, no permission)
            self.logger.warning(f"Stage 1 analysis failed (business logic): {e}")
            return {
                'success': False,
                'error': str(e),
                'error_type': 'business_logic',
                'metadata': {
                    'orchestration': {
                        'action': OrchestrationAction.FAIL_JOB.value,
                        'items': [],
                        'metadata': {'error': str(e)}
                    }
                }
            }

        except Exception as e:
            # Unexpected error
            self.logger.error(f"Stage 1 analysis failed unexpectedly: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return {
                'success': False,
                'error': str(e),
                'error_type': 'unexpected',
                'metadata': {
                    'orchestration': {
                        'action': OrchestrationAction.FAIL_JOB.value,
                        'items': [],
                        'metadata': {'error': str(e)}
                    }
                }
            }

    # ========================================================================
    # QUEUE PROCESSING METHODS (Required by function_app)
    # ========================================================================

    def queue_job(self, job_id: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Queue job to Service Bus.

        Required by submit_job trigger for job submission.
        """
        self.logger.info(f"🚌 Queueing job {job_id} to Service Bus")

        # Get configuration
        from config import AppConfig
        from schema_queue import JobQueueMessage
        import uuid

        config = AppConfig.from_environment()

        # Create job queue message
        queue_message = JobQueueMessage(
            job_id=job_id,
            job_type=self.get_job_type(),
            parameters=parameters,
            stage=1,
            correlation_id=str(uuid.uuid4())[:8]
        )

        # Use Service Bus repository
        from repositories.factory import RepositoryFactory
        service_bus_repo = RepositoryFactory.create_service_bus_repository()
        queue_name = config.job_processing_queue

        try:
            message_id = service_bus_repo.send_message(queue_name, queue_message)
            self.logger.info(f"✅ Job queued with ID: {message_id}")

            return {
                "queued": True,
                "message_id": message_id,
                "queue": queue_name,
                "processing_path": "service_bus",
                "architecture": "clean"
            }

        except Exception as e:
            self.logger.error(f"❌ Failed to queue job: {e}")
            raise RuntimeError(f"Service Bus queueing failed: {e}")

    def process_job_queue_message(self, job_message) -> Dict[str, Any]:
        """
        Process a job queue message by creating and queuing tasks.

        Required by function_app for job queue processing.
        """
        from repositories.factory import RepositoryFactory

        self.logger.info(f"Processing job message: {job_message.job_id}")

        try:
            # Get job record
            repos = RepositoryFactory.create_repositories()
            job_repo = repos['job_repo']
            job_record = job_repo.get_job(job_message.job_id)

            if not job_record:
                raise ValueError(f"Job {job_message.job_id} not found")

            # Update job to PROCESSING
            self.state_manager.update_job_status(
                job_message.job_id,
                'processing'
            )

            # Get previous stage results if needed
            previous_results = None
            if job_message.stage > 1:
                previous_results = self.state_manager.get_stage_results(
                    job_message.job_id,
                    job_message.stage - 1
                )

            # Create tasks for current stage
            tasks = self.create_stage_tasks(
                job_message.stage,
                job_message.job_id,
                job_record.parameters,
                previous_results
            )

            # Queue tasks (batch or individual)
            if len(tasks) >= 50:
                # PLACEHOLDER: _batch_queue_tasks method doesn't exist!
                raise NotImplementedError(
                    "_batch_queue_tasks method not implemented. "
                    "This is a placeholder that needs implementation."
                )
                # self._batch_queue_tasks(tasks, job_message.job_id, job_message.stage)
            else:
                # PLACEHOLDER: Individual task queueing not implemented!
                raise NotImplementedError(
                    "Individual task queueing not implemented in process_job_queue_message. "
                    "This is a placeholder that needs the actual queueing logic."
                )
                # for task in tasks:
                #     # Queue task logic here
                #     pass

            return {
                'success': True,
                'job_id': job_message.job_id,
                'stage': job_message.stage,
                'tasks_created': len(tasks)
            }

        except Exception as e:
            self.logger.error(f"Failed to process job message: {e}")
            self.state_manager.update_job_status(
                job_message.job_id,
                'failed',
                str(e)
            )
            return {
                'success': False,
                'error': str(e)
            }

    def process_task_queue_message(self, task_message) -> Dict[str, Any]:
        """
        Process a task queue message by executing the task.

        Required by function_app for task queue processing.
        Implements "last task turns out the lights" pattern.
        """
        self.logger.info(f"Processing task message: {task_message.task_id}")

        try:
            # Get task handler - needs both task_message and repository
            from task_factory import TaskHandlerFactory
            from repositories.factories import RepositoryFactory
            repos = RepositoryFactory.create_repositories()
            task_repo = repos['task_repo']
            handler = TaskHandlerFactory.get_handler(task_message, task_repo)

            # Execute task - handler expects just parameters
            result = handler(task_message.parameters)

            # Complete task with "last task turns out lights"
            completion = self.state_manager.complete_task_with_sql(
                task_message.task_id,
                task_message.job_id,
                task_message.stage,
                result
            )

            # If this was the last task in stage
            if completion.stage_complete:
                if self.should_advance_stage(
                    task_message.job_id,
                    task_message.stage,
                    {}
                ):
                    # Queue next stage
                    import uuid
                    from schema_queue import JobQueueMessage
                    next_stage_message = JobQueueMessage(
                        job_id=task_message.job_id,
                        job_type=self.get_job_type(),
                        parameters={},
                        stage=task_message.stage + 1,
                        correlation_id=str(uuid.uuid4())[:8]
                    )
                    self.queue_job(task_message.job_id, {})
                else:
                    # Complete job
                    self.state_manager.complete_job(
                        task_message.job_id,
                        self.aggregate_job_results({})
                    )

            return {
                'success': True,
                'task_id': task_message.task_id,
                'stage_complete': completion.stage_complete
            }

        except Exception as e:
            self.logger.error(f"Failed to process task: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def get_performance_summary(self) -> Dict[str, Any]:
        """
        Get performance metrics summary.

        Required by function_app for metrics reporting.
        """
        # PLACEHOLDER: Not fully implemented!
        # Should gather actual metrics from processing
        return {
            'processing_path': 'service_bus',
            'architecture': 'clean',
            'message': 'WARNING: Performance metrics collection not fully implemented',
            'placeholder': True  # Flag to indicate this is placeholder data
        }

    # ========================================================================
    # HELPER METHODS
    # ========================================================================

    def should_advance_stage(
        self,
        job_id: str,
        current_stage: int,
        stage_results: Dict[str, Any]
    ) -> bool:
        """
        Determine if job should advance to next stage.

        For list-then-process, advance from 1→2 if items found.
        """
        if current_stage == 1:
            # Check if Stage 1 found items to process
            metadata = stage_results.get('metadata', {})
            orchestration = metadata.get('orchestration', {})
            action = orchestration.get('action')

            if action == OrchestrationAction.CREATE_TASKS.value:
                return True  # Advance to Stage 2
            else:
                return False  # Complete job

        return False  # Only 2 stages

    def _should_use_batching(self, item_count: int) -> bool:
        """Determine if batch processing should be used."""
        return item_count >= self.DEFAULT_BATCH_THRESHOLD

    # ========================================================================
    # CONCRETE EXAMPLES - Common Implementations
    # ========================================================================


class ContainerListProcessor(ServiceBusListProcessor):
    """
    Example: List container files then process each.

    This is the pattern for:
    - Extract metadata from each file
    - Create STAC items for each file
    - Generate thumbnails for each image
    """

    def get_job_type(self) -> str:
        return "list_container"

    def validate_job_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Validate container listing parameters."""
        # Get config for default container name
        from config import get_config
        config = get_config()

        return {
            'container': parameters.get('container', config.bronze_container_name),
            'prefix': parameters.get('prefix', ''),
            'extension_filter': parameters.get('extension_filter', ''),
            'limit': min(10000, parameters.get('limit', 1000))
        }

    def analyze_source(self, parameters: Dict[str, Any]) -> List[FileOrchestrationItem]:
        """List container files."""
        # Import here to avoid circular dependency
        from repositories.factory import RepositoryFactory

        # Get blob repository
        repos = RepositoryFactory.create_repositories()
        blob_repo = repos.get('blob_repo')

        # List files
        files = blob_repo.list_blobs(
            container=parameters['container'],
            prefix=parameters.get('prefix', ''),
            limit=parameters.get('limit', 1000)
        )

        # Filter by extension if specified
        extension = parameters.get('extension_filter', '')
        if extension:
            files = [f for f in files if f['name'].endswith(extension)]

        # Convert to orchestration items
        items = []
        for file_info in files:
            item = FileOrchestrationItem(
                container=parameters['container'],
                path=file_info['name'],
                size=file_info.get('size', 0),
                last_modified=file_info.get('last_modified'),
                content_type=file_info.get('content_type')
            )
            items.append(item)

        self.logger.info(f"Found {len(items)} files to process")
        return items


class STACIngestionProcessor(ServiceBusListProcessor):
    """
    Example: List container then create STAC metadata for each file.
    """

    def get_job_type(self) -> str:
        return "stac_ingestion"

    def get_stage_2_task_type(self) -> str:
        return "create_stac_item"

    def validate_job_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Validate STAC ingestion parameters."""
        # Get config for default container name
        from config import get_config
        config = get_config()

        return {
            'container': parameters.get('container', config.bronze_container_name),
            'collection': parameters.get('collection', 'bronze'),
            'file_types': parameters.get('file_types', ['.tif', '.tiff']),
            'extract_metadata': parameters.get('extract_metadata', True)
        }

    def analyze_source(self, parameters: Dict[str, Any]) -> List[FileOrchestrationItem]:
        """List raster files for STAC ingestion."""
        # PLACEHOLDER: Not implemented!
        raise NotImplementedError(
            "STACIngestionProcessor.analyze_source() is a placeholder. "
            "Needs actual implementation to list and filter raster files."
        )
        # Similar to ContainerListProcessor but filters for raster files
        # Implementation would list files and filter by type
        # pass  # Implement based on specific needs


class GeoJSONBatchProcessor(ServiceBusListProcessor):
    """
    Example: Read GeoJSON then split into batches for PostGIS upload.
    """

    def get_job_type(self) -> str:
        return "geojson_batch_upload"

    def get_stage_2_task_type(self) -> str:
        return "upload_feature_batch"

    def validate_job_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Validate GeoJSON processing parameters."""
        return {
            'source_file': parameters['source_file'],  # Required
            'target_table': parameters.get('target_table', 'features'),
            'batch_size': min(1000, parameters.get('batch_size', 100)),
            'srid': parameters.get('srid', 4326)
        }

    def analyze_source(self, parameters: Dict[str, Any]) -> List[OrchestrationItem]:
        """
        Read GeoJSON and split into batches.

        Each orchestration item represents a batch of features.
        """
        import json

        # Read GeoJSON (simplified example)
        # In production, stream large files
        with open(parameters['source_file'], 'r') as f:
            geojson = json.load(f)

        features = geojson.get('features', [])
        batch_size = parameters['batch_size']

        # Create orchestration items for each batch
        items = []
        for i in range(0, len(features), batch_size):
            batch = features[i:i + batch_size]

            # Create item representing this batch
            item = OrchestrationItem(
                item_id=f"batch_{i//batch_size:04d}",
                item_type="feature_batch",
                metadata={
                    'batch_index': i // batch_size,
                    'feature_count': len(batch),
                    'start_index': i,
                    'end_index': i + len(batch),
                    # Store batch data or reference
                    'features': batch  # Or store in blob and pass URL
                }
            )
            items.append(item)

        self.logger.info(f"Split {len(features)} features into {len(items)} batches")
        return items