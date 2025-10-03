# ============================================================================
# CLAUDE CONTEXT - ORCHESTRATION
# ============================================================================
# CATEGORY: STATE MANAGEMENT & ORCHESTRATION
# PURPOSE: Core architectural component for job/task lifecycle management
# EPOCH: Shared by all epochs (may evolve with architecture changes)# PURPOSE: Simplified dynamic orchestration optimized for Service Bus batch processing
# EXPORTS: OrchestrationManager - handles dynamic task creation with batching
# INTERFACES: Works with CoreController for stage-based task generation
# PYDANTIC_MODELS: OrchestrationInstruction, FileOrchestrationItem, TaskDefinition
# DEPENDENCIES: typing, logging, schema_orchestration
# SOURCE: Extracted and simplified from BaseController for Service Bus optimization
# SCOPE: Dynamic task creation based on Stage 1 analysis results
# VALIDATION: Pydantic models ensure data consistency
# PATTERNS: Strategy pattern for different orchestration actions
# ENTRY_POINTS: Used by Service Bus controllers for dynamic workflows
# INDEX: OrchestrationManager:50, parse_stage_results:150, create_batch_tasks:250
# ============================================================================

"""
Orchestration Manager - Dynamic Task Creation for Service Bus

Simplified orchestration for Service Bus controllers that need dynamic
task creation (like container operations). Optimized for batch processing.

Key Pattern:
- Stage 1: Analyze (e.g., list container files)
- Stage 2: Process items in batches (e.g., extract metadata)

This is much simpler than BaseController's orchestration because:
1. No workflow definitions needed
2. Optimized for batch creation
3. Direct integration with Service Bus batching

Author: Robert and Geospatial Claude Legion
Date: 26 SEP 2025
"""

from typing import Dict, Any, List, Optional, Tuple
import logging
from dataclasses import dataclass

# Pydantic models - using new core.models structure
from core.models import TaskDefinition
from core.schema import (
    OrchestrationInstruction,
    OrchestrationAction,
    FileOrchestrationItem,
    OrchestrationItem
)

# Logging
from util_logger import LoggerFactory, ComponentType


class OrchestrationManager:
    """
    Manages dynamic task creation for Service Bus controllers.

    Simplified version of BaseController's orchestration, optimized for:
    - Batch processing (100-item aligned batches)
    - Container operations (list/analyze patterns)
    - Service Bus performance

    Usage:
        orchestrator = OrchestrationManager()

        # In Stage 1: Return orchestration instruction
        items = analyze_container()
        instruction = orchestrator.create_instruction(items)

        # In Stage 2: Create tasks from instruction
        tasks = orchestrator.create_tasks_from_instruction(
            instruction, job_id, stage=2
        )
    """

    BATCH_SIZE = 100  # Aligned with Service Bus limits

    def __init__(self, job_type: str):
        """
        Initialize orchestration manager.

        Args:
            job_type: Type of job (for task creation)
        """
        self.job_type = job_type
        self.logger = LoggerFactory.create_logger(
            ComponentType.CONTROLLER,
            f"OrchestrationManager-{job_type}"
        )

    # ========================================================================
    # CREATING ORCHESTRATION INSTRUCTIONS (Stage 1 Output)
    # ========================================================================

    def create_instruction(
        self,
        items: List[Any],
        action: OrchestrationAction = OrchestrationAction.CREATE_TASKS,
        stage_2_parameters: Optional[Dict[str, Any]] = None
    ) -> OrchestrationInstruction:
        """
        Create orchestration instruction from Stage 1 analysis.

        Args:
            items: Items to process (files, records, etc.)
            action: What Stage 2 should do
            stage_2_parameters: Additional params for Stage 2

        Returns:
            OrchestrationInstruction for Stage 2
        """
        self.logger.info(f"Creating orchestration with {len(items)} items")

        # Convert items to orchestration items
        orchestration_items = []
        for item in items:
            if isinstance(item, (OrchestrationItem, FileOrchestrationItem)):
                orchestration_items.append(item)
            elif isinstance(item, dict):
                # Try to create FileOrchestrationItem from dict
                if 'path' in item and 'container' in item:
                    orchestration_items.append(FileOrchestrationItem(**item))
                else:
                    # Generic orchestration item
                    orchestration_items.append(OrchestrationItem(
                        item_id=item.get('id', str(hash(str(item)))),
                        item_type=item.get('type', 'unknown'),
                        metadata=item
                    ))
            else:
                # Create generic item
                orchestration_items.append(OrchestrationItem(
                    item_id=str(hash(str(item))),
                    item_type=type(item).__name__,
                    metadata={'value': str(item)}
                ))

        instruction = OrchestrationInstruction(
            action=action,
            items=orchestration_items,
            stage_2_parameters=stage_2_parameters or {},
            metadata={
                'total_items': len(orchestration_items),
                'job_type': self.job_type
            }
        )

        self.logger.info(f"Created instruction: action={action}, items={len(orchestration_items)}")
        return instruction

    def create_file_items(
        self,
        files: List[Dict[str, Any]],
        container: str
    ) -> List[FileOrchestrationItem]:
        """
        Create FileOrchestrationItems from file listings.

        Specialized for container operations.

        Args:
            files: List of file info dicts
            container: Container name

        Returns:
            List of FileOrchestrationItems
        """
        items = []
        for file_info in files:
            item = FileOrchestrationItem(
                container=container,
                path=file_info['name'],
                size=file_info.get('size', 0),
                last_modified=file_info.get('last_modified'),
                content_type=file_info.get('content_type'),
                metadata=file_info.get('metadata', {})
            )
            items.append(item)

        self.logger.debug(f"Created {len(items)} file orchestration items")
        return items

    # ========================================================================
    # PARSING ORCHESTRATION INSTRUCTIONS (Stage 2 Input)
    # ========================================================================

    def parse_stage_results(
        self,
        stage_results: Dict[str, Any]
    ) -> Optional[OrchestrationInstruction]:
        """
        Parse orchestration instruction from Stage 1 results.

        Args:
            stage_results: Results from Stage 1

        Returns:
            OrchestrationInstruction or None
        """
        # CONTRACT ENFORCEMENT - Validate input type
        from exceptions import ContractViolationError
        from pydantic import ValidationError

        if not isinstance(stage_results, dict):
            raise ContractViolationError(
                f"Contract violation in OrchestrationManager.parse_stage_results: "
                f"stage_results must be dict, got {type(stage_results).__name__}"
            )

        # Check for orchestration in metadata (StageResultContract pattern)
        metadata = stage_results.get('metadata', {})
        orchestration_data = metadata.get('orchestration')

        if not orchestration_data:
            self.logger.debug("No orchestration data in stage results")
            return None  # This is valid - not all stages have orchestration

        try:
            # Parse into OrchestrationInstruction
            if isinstance(orchestration_data, dict):
                instruction = OrchestrationInstruction(**orchestration_data)
            else:
                instruction = OrchestrationInstruction.model_validate(orchestration_data)

            self.logger.info(
                f"Parsed orchestration: action={instruction.action}, "
                f"items={len(instruction.items)}"
            )
            return instruction

        except ValidationError as e:
            # Pydantic validation failed - this is a contract violation
            raise ContractViolationError(
                f"Contract violation: Invalid orchestration data structure. "
                f"Expected OrchestrationInstruction schema, got malformed data. "
                f"Validation errors: {e.errors()}"
            )

        except Exception as e:
            # Unexpected error during parsing
            self.logger.error(f"Unexpected error parsing orchestration: {e}")
            raise ContractViolationError(
                f"Contract violation: Failed to parse orchestration data. "
                f"Error: {str(e)}. Data type: {type(orchestration_data).__name__}"
            )

    # ========================================================================
    # CREATING TASKS FROM ORCHESTRATION (Stage 2 Processing)
    # ========================================================================

    def create_tasks_from_instruction(
        self,
        instruction: OrchestrationInstruction,
        job_id: str,
        stage: int,
        job_parameters: Dict[str, Any]
    ) -> List[TaskDefinition]:
        """
        Create tasks from orchestration instruction.

        Optimized for batch processing with Service Bus.

        Args:
            instruction: Orchestration from Stage 1
            job_id: Parent job ID
            stage: Current stage number
            job_parameters: Original job parameters

        Returns:
            List of TaskDefinition objects
        """
        if instruction.action != OrchestrationAction.CREATE_TASKS:
            self.logger.info(f"Action is {instruction.action}, not creating tasks")
            return []

        if not instruction.items:
            self.logger.warning("No items in orchestration")
            return []

        self.logger.info(f"Creating tasks for {len(instruction.items)} items")

        tasks = []
        for idx, item in enumerate(instruction.items):
            # Create task ID
            task_id = self._generate_task_id(job_id, stage, idx, item)

            # Build task parameters
            task_params = self._build_task_parameters(
                item,
                job_parameters,
                instruction.stage_2_parameters,
                idx
            )

            # Create task definition
            task = TaskDefinition(
                task_id=task_id,
                job_id=job_id,
                job_type=self.job_type,
                task_type=self._get_task_type(instruction, stage),
                stage_number=stage,
                parameters=task_params
            )
            tasks.append(task)

        self.logger.info(f"Created {len(tasks)} tasks")
        return tasks

    def create_batch_tasks(
        self,
        instruction: OrchestrationInstruction,
        job_id: str,
        stage: int,
        job_parameters: Dict[str, Any]
    ) -> List[List[TaskDefinition]]:
        """
        Create tasks in aligned batches for Service Bus.

        Returns tasks grouped in BATCH_SIZE chunks for efficient
        batch processing with Service Bus.

        Args:
            instruction: Orchestration from Stage 1
            job_id: Parent job ID
            stage: Current stage number
            job_parameters: Original job parameters

        Returns:
            List of task batches (each batch has up to BATCH_SIZE tasks)
        """
        all_tasks = self.create_tasks_from_instruction(
            instruction, job_id, stage, job_parameters
        )

        if not all_tasks:
            return []

        # Group into batches
        batches = []
        for i in range(0, len(all_tasks), self.BATCH_SIZE):
            batch = all_tasks[i:i + self.BATCH_SIZE]
            batches.append(batch)

        self.logger.info(
            f"Created {len(batches)} batches "
            f"({len(all_tasks)} tasks total)"
        )
        return batches

    # ========================================================================
    # HELPER METHODS
    # ========================================================================

    def _generate_task_id(
        self,
        job_id: str,
        stage: int,
        index: int,
        item: OrchestrationItem
    ) -> str:
        """Generate unique task ID."""
        # Use item ID if available (for deterministic IDs)
        if hasattr(item, 'item_id') and item.item_id:
            suffix = f"item-{item.item_id[:8]}"
        else:
            suffix = f"idx-{index:04d}"

        return f"{job_id[:8]}-s{stage}-{suffix}"

    def _build_task_parameters(
        self,
        item: OrchestrationItem,
        job_params: Dict[str, Any],
        stage_params: Dict[str, Any],
        index: int
    ) -> Dict[str, Any]:
        """Build parameters for a task."""
        params = {
            **job_params,  # Original job parameters
            **stage_params,  # Stage 2 specific parameters
            'task_index': index
        }

        # Add item-specific fields
        if isinstance(item, FileOrchestrationItem):
            params.update({
                'container': item.container,
                'file_path': item.path,
                'file_size': item.size,
                'last_modified': item.last_modified.isoformat() if item.last_modified else None
            })
        else:
            # Generic item
            params.update({
                'item_id': item.item_id,
                'item_type': item.item_type,
                'item_metadata': item.metadata
            })

        return params

    def _get_task_type(
        self,
        instruction: OrchestrationInstruction,
        stage: int
    ) -> str:
        """Determine task type for the stage."""
        # Check if task type specified in instruction
        if instruction.stage_2_parameters.get('task_type'):
            return instruction.stage_2_parameters['task_type']

        # Default task types by job type
        task_type_map = {
            'list_container': 'extract_metadata',
            'process_container': 'process_file',
            'analyze_container': 'analyze_file'
        }

        return task_type_map.get(self.job_type, f'stage_{stage}_task')

    # ========================================================================
    # BATCH OPTIMIZATION HELPERS
    # ========================================================================

    def estimate_batch_count(self, item_count: int) -> int:
        """Estimate number of batches needed."""
        return (item_count + self.BATCH_SIZE - 1) // self.BATCH_SIZE

    def should_use_batching(self, item_count: int) -> bool:
        """Determine if batch processing should be used."""
        # Use batching if more than 50 items
        return item_count >= 50