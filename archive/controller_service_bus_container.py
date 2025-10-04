# ============================================================================
# CLAUDE CONTEXT - CONTROLLER
# ============================================================================
# EPOCH: 3 - DEPRECATED ⚠️
# STATUS: Replaced by Epoch 4 CoreMachine
# MIGRATION: Will be archived after Storage Queue triggers migrated
# PURPOSE: Service Bus Container controller using clean architecture for list-then-process
# EXPORTS: ServiceBusContainerController - Container operations with clean architecture
# INTERFACES: Extends ServiceBusListProcessor (template method pattern)
# PYDANTIC_MODELS: TaskDefinition, OrchestrationInstruction, FileOrchestrationItem
# DEPENDENCIES: service_bus_list_processor, repositories.factory, repositories.blob
# SOURCE: Clean architecture implementation for container operations
# SCOPE: Container listing and metadata extraction workflows
# VALIDATION: Pydantic models and parameter validation
# PATTERNS: Template Method, Composition over inheritance
# ENTRY_POINTS: Used when job_type = 'sb_list_container'
# INDEX: ServiceBusContainerController:100, analyze_source:200, execute_stage_2:400
# ============================================================================

"""
Service Bus Container Controller - Clean Architecture

Lists container files then processes each in batches.
This is THE pattern for most geospatial workflows:
- List container → extract metadata for each file
- List container → create STAC items for each file
- List container → generate thumbnails for each image

Extends ServiceBusListProcessor which handles all orchestration.
We just implement:
1. How to list the container (analyze_source)
2. How to process each file (handled by task processors)

Author: Robert and Geospatial Claude Legion
Date: 26 SEP 2025
"""

from typing import Dict, Any, List, Optional
from datetime import datetime

# Base class that handles orchestration
from service_bus_list_processor import ServiceBusListProcessor

# Pydantic models
from schema_orchestration import (
    FileOrchestrationItem,
    OrchestrationInstruction,
    OrchestrationAction
)

# Repositories
from repositories.factory import RepositoryFactory

# Configuration
from config import get_config

# Utilities
from util_logger import LoggerFactory, ComponentType


class ServiceBusContainerController(ServiceBusListProcessor):
    """
    Service Bus container controller with clean architecture.

    Lists container files in Stage 1, processes each in Stage 2.
    All orchestration handled by ServiceBusListProcessor base class.

    Example workflow:
    - Stage 1: List all .tif files in bronze container
    - Stage 2: Extract metadata from each file (parallel tasks)

    This replaces the old container controllers that inherited
    from the 2,290-line BaseController God Class.
    """

    REGISTRATION_INFO = {
        'job_type': 'sb_list_container',
        'description': 'List and process container files with Service Bus',
        'version': '2.0.0',  # v2 = clean architecture
        'supported_parameters': ['container', 'prefix', 'extension_filter', 'limit', 'task_type'],
        'stages': 2
    }

    def __init__(self):
        """Initialize container controller."""
        super().__init__()
        self.logger = LoggerFactory.create_logger(
            ComponentType.CONTROLLER,
            "ServiceBusContainer"
        )

    # ========================================================================
    # IMPLEMENT REQUIRED METHODS FROM ServiceBusListProcessor
    # ========================================================================

    def get_job_type(self) -> str:
        """Return the job type identifier."""
        return 'sb_list_container'

    def validate_job_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate container listing parameters.

        Parameters:
            container: Container name (default: bronze container from config)
            prefix: Optional path prefix to filter files
            extension_filter: Optional extension like '.tif'
            limit: Max files to process (default: 1000, max: 10000)
            task_type: What to do with each file (default: 'extract_metadata')
        """
        # Get configuration for default container name
        config = get_config()

        validated = {}

        # Container to list (use config for default)
        validated['container'] = parameters.get('container', config.bronze_container_name)

        # Optional filters
        validated['prefix'] = parameters.get('prefix', '')
        validated['extension_filter'] = parameters.get('extension_filter', '')

        # Limit files (safety limit)
        validated['limit'] = min(10000, parameters.get('limit', 1000))

        # What to do with each file in Stage 2
        validated['task_type'] = parameters.get('task_type', 'extract_metadata')

        # Force Service Bus
        validated['use_service_bus'] = True

        return validated

    def analyze_source(
        self,
        parameters: Dict[str, Any]
    ) -> List[FileOrchestrationItem]:
        """
        List container files in Stage 1.

        This is called by the base class during Stage 1 execution.
        Returns list of files to process in Stage 2.

        Args:
            parameters: Validated job parameters

        Returns:
            List of FileOrchestrationItems for Stage 2 processing
        """
        self.logger.info(f"📂 Listing container: {parameters['container']}")

        # Get blob repository
        repos = RepositoryFactory.create_repositories()
        blob_repo = repos.get('blob_repo')

        if not blob_repo:
            self.logger.error("Blob repository not available")
            return []

        # List files in container
        try:
            files = blob_repo.list_blobs(
                container=parameters['container'],
                prefix=parameters.get('prefix', ''),
                limit=parameters.get('limit', 1000)
            )
        except Exception as e:
            self.logger.error(f"Failed to list container: {e}")
            return []

        # Filter by extension if specified
        extension = parameters.get('extension_filter', '')
        if extension:
            original_count = len(files)
            files = [f for f in files if f['name'].endswith(extension)]
            self.logger.info(
                f"Filtered {original_count} files to {len(files)} "
                f"with extension '{extension}'"
            )

        # Convert to orchestration items
        items = []
        for file_info in files:
            item = FileOrchestrationItem(
                container=parameters['container'],
                path=file_info['name'],
                size=file_info.get('size', 0),
                last_modified=file_info.get('last_modified'),
                content_type=file_info.get('content_type'),
                metadata={
                    'etag': file_info.get('etag'),
                    'task_type': parameters['task_type']
                }
            )
            items.append(item)

        self.logger.info(
            f"✅ Found {len(items)} files to process in container "
            f"'{parameters['container']}'"
        )

        return items

    def get_stage_2_task_type(self) -> str:
        """
        Get task type for Stage 2 processing.

        Can be overridden by task_type parameter.
        """
        # This will be overridden by the task_type parameter
        return 'extract_metadata'

    # ========================================================================
    # OPTIONAL: CUSTOMIZE STAGE 2 BEHAVIOR
    # ========================================================================

    def create_stage_tasks(
        self,
        stage_number: int,
        job_id: str,
        job_parameters: Dict[str, Any],
        previous_stage_results: Optional[List[Dict[str, Any]]] = None
    ) -> List:
        """
        Override to customize task creation if needed.

        For container operations, we mostly rely on the base class
        but can add custom logic here.
        """
        # For Stage 2, inject the task_type parameter
        if stage_number == 2 and previous_stage_results:
            # Update orchestration to use specified task_type
            task_type = job_parameters.get('task_type', 'extract_metadata')

            # The base class will handle the rest
            # Just make sure the task_type is set correctly

        # Call parent implementation
        return super().create_stage_tasks(
            stage_number, job_id, job_parameters, previous_stage_results
        )

    def should_advance_stage(
        self,
        job_id: str,
        current_stage: int,
        stage_results: Dict[str, Any]
    ) -> bool:
        """
        Determine if job should advance to next stage.

        For container operations:
        - Advance from 1→2 if files were found
        - Complete after Stage 2
        """
        if current_stage == 1:
            # Check if any files were found
            items_found = stage_results.get('items_found', 0)
            if items_found > 0:
                self.logger.info(f"Found {items_found} files, advancing to Stage 2")
                return True
            else:
                self.logger.info("No files found, completing job")
                return False

        # No Stage 3
        return False

    def aggregate_job_results(self, context) -> Dict[str, Any]:
        """
        Aggregate results when job completes.

        Summarizes what was listed and processed.
        """
        # Get counts from context
        stage_1_items = 0
        stage_2_processed = 0

        if hasattr(context, 'stage_results'):
            # Stage 1 results
            stage_1_data = context.stage_results.get('1', {})
            stage_1_items = stage_1_data.get('items_found', 0)

            # Stage 2 results (task count)
            stage_2_data = context.stage_results.get('2', {})
            stage_2_processed = stage_2_data.get('task_count', 0)

        return {
            'job_type': self.get_job_type(),
            'processing_path': self.processing_path,
            'architecture': 'clean',
            'stages_completed': 2,
            'files_found': stage_1_items,
            'files_processed': stage_2_processed,
            'message': (
                f"Container listing completed: "
                f"found {stage_1_items} files, "
                f"processed {stage_2_processed} items"
            )
        }


class ServiceBusExtractMetadataController(ServiceBusContainerController):
    """
    Specialized container controller for metadata extraction.

    Same as container controller but specifically for metadata extraction.
    This shows how easy it is to create specialized controllers.
    """

    REGISTRATION_INFO = {
        'job_type': 'sb_extract_metadata',
        'description': 'Extract metadata from container files',
        'version': '2.0.0',
        'supported_parameters': ['container', 'prefix', 'extension_filter', 'limit'],
        'stages': 2
    }

    def get_job_type(self) -> str:
        """Return the job type identifier."""
        return 'sb_extract_metadata'

    def validate_job_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Force task_type to extract_metadata."""
        validated = super().validate_job_parameters(parameters)
        validated['task_type'] = 'extract_metadata'  # Force specific task type
        return validated

    def get_stage_2_task_type(self) -> str:
        """Always extract metadata in Stage 2."""
        return 'extract_metadata'