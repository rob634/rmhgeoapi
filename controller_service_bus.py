# ============================================================================
# CLAUDE CONTEXT - CONTROLLER
# ============================================================================
# PURPOSE: Service Bus-optimized base controller with batch processing support
# EXPORTS: ServiceBusBaseController - Enhanced controller for Service Bus pipeline
# INTERFACES: Extends BaseController with batch processing capabilities
# PYDANTIC_MODELS: Uses same models as BaseController (JobRecord, TaskRecord, etc.)
# DEPENDENCIES: controller_base, repositories.service_bus, repositories.jobs_tasks
# SOURCE: Inherits from BaseController, adds Service Bus-specific optimizations
# SCOPE: High-volume job orchestration with batch processing
# VALIDATION: Same as BaseController plus batch size validation
# PATTERNS: Template Method, Strategy (batch vs individual processing)
# ENTRY_POINTS: Used when use_service_bus=true parameter is set
# INDEX: ServiceBusBaseController:50, batch_queue_stage_tasks:200, process_batch:350
# ============================================================================

"""
Service Bus Base Controller

Optimized controller for Service Bus pipeline with batch processing.
Inherits from BaseController and adds:
- Batch task creation and queuing
- Aligned 100-item batch processing
- Service Bus-specific queue routing
- Performance metrics tracking

This controller is used when jobs are submitted with use_service_bus=true.

Author: Robert and Geospatial Claude Legion
Date: 25 SEP 2025
"""

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone
from abc import abstractmethod
import time
import logging

from controller_base import BaseController
from schema_base import TaskDefinition, TaskRecord, TaskStatus
from schema_queue import TaskQueueMessage
from repositories.factory import RepositoryFactory
from repositories.service_bus import BatchResult
from config import AppConfig
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "ServiceBusController")


class ServiceBusBaseController(BaseController):
    """
    Service Bus-optimized controller with batch processing.

    Key Features:
    - Inherits all BaseController functionality
    - Adds batch processing for high-volume scenarios
    - Uses Service Bus repository for queue operations
    - Aligns batches to 100 items (Service Bus limit)
    - Tracks performance metrics per batch

    Usage:
        When job_params contains use_service_bus=true,
        the factory creates a controller instance that inherits
        from this class instead of BaseController.
    """

    # Batch configuration
    BATCH_SIZE = 100  # Aligned with Service Bus limit
    BATCH_THRESHOLD = 50  # Use batching if >= 50 tasks

    def __init__(self):
        """Initialize Service Bus controller."""
        super().__init__()
        self.processing_path = 'service_bus'
        self.batch_metrics = []

    # ========================================================================
    # OVERRIDE: Queue Selection
    # ========================================================================

    def queue_job(self, job_id: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Queue job using Service Bus instead of Queue Storage.

        Overrides BaseController.queue_job() to use Service Bus repository
        and queue names with 'sb-' prefix.

        Args:
            job_id: Job identifier
            parameters: Job parameters including use_service_bus flag

        Returns:
            Queue result with Service Bus message ID
        """
        self.logger.info(f"🚌 Queueing job {job_id} to Service Bus")

        # Get configuration
        config = AppConfig.from_environment()

        # Create job queue message
        from schema_queue import JobQueueMessage
        queue_message = JobQueueMessage(
            job_id=job_id,
            job_type=self._job_type,
            parameters=parameters,
            stage=1,
            correlation_id=self._generate_correlation_id()
        )

        # Use Service Bus repository with same queue names as Storage
        self.logger.debug(f"📦 Creating Service Bus repository")
        queue_repo = RepositoryFactory.create_service_bus_repository()
        queue_name = config.job_processing_queue  # Same name as Storage Queue

        self.logger.debug(f"📬 Queue name: {queue_name}")
        self.logger.debug(f"📋 Queue message type: {type(queue_message).__name__}")
        self.logger.debug(f"📝 Queue message job_id: {queue_message.job_id}")

        try:
            self.logger.debug(f"📤 Calling queue_repo.send_message()")
            message_id = queue_repo.send_message(queue_name, queue_message)
            self.logger.info(f"✅ Job queued to Service Bus with ID: {message_id}")

            return {
                "queued": True,
                "message_id": message_id,
                "queue": queue_name,
                "processing_path": self.processing_path
            }

        except Exception as e:
            self.logger.error(f"❌ Failed to queue job to Service Bus: {e}")
            raise RuntimeError(f"Service Bus queueing failed: {e}")

    # ========================================================================
    # OVERRIDE: Task Creation with Batching
    # ========================================================================

    def queue_stage_tasks(
        self,
        job_id: str,
        stage_number: int,
        job_parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Queue stage tasks with batch optimization.

        Overrides BaseController to add batch processing when task count
        exceeds threshold. Uses aligned 100-item batches for optimal
        coordination between PostgreSQL and Service Bus.

        Args:
            job_id: Job identifier
            stage_number: Current stage number
            job_parameters: Job parameters

        Returns:
            Result dictionary with batch processing metrics
        """
        self.logger.info(f"📦 Creating tasks for stage {stage_number}")

        # Get previous stage results if needed
        previous_results = None
        if stage_number > 1:
            repos = RepositoryFactory.create_repositories()
            previous_results = self._get_previous_stage_results(
                job_id, stage_number - 1, repos['task_repo']
            )

        # Create task definitions
        task_definitions = self.create_stage_tasks(
            stage_number=stage_number,
            job_id=job_id,
            job_parameters=job_parameters,
            previous_stage_results=previous_results
        )

        if not task_definitions:
            return {
                "tasks_created": 0,
                "message": "No tasks to create"
            }

        # Decide on processing strategy
        task_count = len(task_definitions)
        self.logger.info(f"📊 Stage {stage_number} has {task_count} tasks")

        if task_count >= self.BATCH_THRESHOLD:
            # Use batch processing
            self.logger.info(f"🚀 Using batch processing for {task_count} tasks")
            return self._batch_queue_stage_tasks(
                task_definitions, job_id, stage_number
            )
        else:
            # Use individual processing for small task sets
            self.logger.info(f"📝 Using individual processing for {task_count} tasks")
            return self._individual_queue_stage_tasks(
                task_definitions, job_id, stage_number
            )

    def _batch_queue_stage_tasks(
        self,
        task_definitions: List[TaskDefinition],
        job_id: str,
        stage_number: int
    ) -> Dict[str, Any]:
        """
        Process tasks in aligned 100-item batches.

        Each batch is processed atomically:
        1. Batch insert to PostgreSQL
        2. Batch send to Service Bus
        3. Status update on success

        Args:
            task_definitions: All task definitions for the stage
            job_id: Job identifier
            stage_number: Current stage

        Returns:
            Detailed batch processing results
        """
        start_time = time.time()
        total_tasks = len(task_definitions)
        successful_batches = []
        failed_batches = []

        # Get repositories
        repos = RepositoryFactory.create_repositories()
        task_repo = repos['task_repo']
        service_bus_repo = RepositoryFactory.create_service_bus_repository()

        # Get queue name (same as Storage Queue names)
        config = AppConfig.from_environment()
        queue_name = config.task_processing_queue  # Using same names as Storage Queues

        # Process in aligned batches
        for i in range(0, total_tasks, self.BATCH_SIZE):
            batch = task_definitions[i:i + self.BATCH_SIZE]
            batch_id = f"{job_id}-s{stage_number}-b{i//self.BATCH_SIZE}"
            batch_start = time.time()

            try:
                # Phase 1: Batch insert to PostgreSQL
                self.logger.debug(f"📥 Inserting batch {batch_id}: {len(batch)} tasks")
                task_records = task_repo.batch_create_tasks(
                    batch,
                    batch_id=batch_id,
                    initial_status='pending_queue'
                )

                # Phase 2: Batch send to Service Bus
                self.logger.debug(f"📤 Sending batch {batch_id} to Service Bus")
                messages = [td.to_queue_message() for td in batch]
                result = service_bus_repo.batch_send_messages(
                    queue_name,
                    messages
                )

                if result.success:
                    # Phase 3: Update status to queued
                    task_ids = [tr.task_id for tr in task_records]
                    updated = task_repo.batch_update_status(
                        task_ids,
                        'queued',
                        {'queued_at': datetime.now(timezone.utc)}
                    )

                    batch_time = (time.time() - batch_start) * 1000
                    successful_batches.append({
                        'batch_id': batch_id,
                        'size': len(batch),
                        'elapsed_ms': batch_time
                    })

                    self.logger.info(
                        f"✅ Batch {batch_id}: {len(batch)} tasks "
                        f"processed in {batch_time:.0f}ms"
                    )
                else:
                    # Queue send failed - tasks remain in pending_queue
                    failed_batches.append({
                        'batch_id': batch_id,
                        'size': len(batch),
                        'error': result.errors
                    })

                    self.logger.error(f"❌ Batch {batch_id} failed: {result.errors}")

            except Exception as e:
                # Batch failed completely
                failed_batches.append({
                    'batch_id': batch_id,
                    'size': len(batch),
                    'error': str(e)
                })

                self.logger.error(f"❌ Batch {batch_id} exception: {e}")

        # Calculate metrics
        elapsed_ms = (time.time() - start_time) * 1000
        tasks_queued = sum(b['size'] for b in successful_batches)
        tasks_failed = sum(b['size'] for b in failed_batches)

        # Store metrics for monitoring
        self.batch_metrics.append({
            'job_id': job_id,
            'stage': stage_number,
            'total_tasks': total_tasks,
            'successful_batches': len(successful_batches),
            'failed_batches': len(failed_batches),
            'tasks_queued': tasks_queued,
            'tasks_failed': tasks_failed,
            'elapsed_ms': elapsed_ms,
            'throughput': tasks_queued / (elapsed_ms / 1000) if elapsed_ms > 0 else 0
        })

        return {
            'status': 'completed' if not failed_batches else 'partial',
            'total_tasks': total_tasks,
            'tasks_queued': tasks_queued,
            'tasks_failed': tasks_failed,
            'batches': {
                'total': len(successful_batches) + len(failed_batches),
                'successful': len(successful_batches),
                'failed': len(failed_batches)
            },
            'performance': {
                'elapsed_ms': elapsed_ms,
                'tasks_per_second': tasks_queued / (elapsed_ms / 1000) if elapsed_ms > 0 else 0,
                'avg_batch_ms': elapsed_ms / len(successful_batches) if successful_batches else 0
            },
            'processing_path': self.processing_path,
            'batch_details': {
                'successful': successful_batches,
                'failed': failed_batches
            }
        }

    def _individual_queue_stage_tasks(
        self,
        task_definitions: List[TaskDefinition],
        job_id: str,
        stage_number: int
    ) -> Dict[str, Any]:
        """
        Queue tasks individually (for small task counts).

        Falls back to parent implementation but uses Service Bus repository.

        Args:
            task_definitions: Task definitions to queue
            job_id: Job identifier
            stage_number: Current stage

        Returns:
            Queue results
        """
        # For small batches, use Service Bus but process individually
        repos = RepositoryFactory.create_repositories()
        task_repo = repos['task_repo']
        service_bus_repo = RepositoryFactory.create_service_bus_repository()

        config = AppConfig.from_environment()
        queue_name = config.task_processing_queue  # Use same name as batch method

        queued_count = 0
        failed_count = 0

        for task_def in task_definitions:
            try:
                # Create task in database
                task_record = task_repo.create_task_from_definition(task_def)

                # Send to Service Bus
                message = task_def.to_queue_message()
                message_id = service_bus_repo.send_message(queue_name, message)

                queued_count += 1
                self.logger.debug(f"✅ Task {task_def.task_id} queued")

            except Exception as e:
                failed_count += 1
                self.logger.error(f"❌ Failed to queue task {task_def.task_id}: {e}")

        return {
            'status': 'completed' if failed_count == 0 else 'partial',
            'total_tasks': len(task_definitions),
            'tasks_queued': queued_count,
            'tasks_failed': failed_count,
            'processing_path': self.processing_path,
            'method': 'individual'
        }

    # ========================================================================
    # Performance Metrics
    # ========================================================================

    def get_batch_metrics(self) -> List[Dict[str, Any]]:
        """
        Get batch processing metrics for this controller instance.

        Returns:
            List of batch metric dictionaries
        """
        return self.batch_metrics

    def get_performance_summary(self) -> Dict[str, Any]:
        """
        Get summary of batch processing performance.

        Returns:
            Performance summary with averages and totals
        """
        if not self.batch_metrics:
            return {
                'message': 'No batch operations performed',
                'processing_path': self.processing_path
            }

        total_tasks = sum(m['total_tasks'] for m in self.batch_metrics)
        total_queued = sum(m['tasks_queued'] for m in self.batch_metrics)
        total_failed = sum(m['tasks_failed'] for m in self.batch_metrics)
        total_time = sum(m['elapsed_ms'] for m in self.batch_metrics)
        avg_throughput = total_queued / (total_time / 1000) if total_time > 0 else 0

        return {
            'processing_path': self.processing_path,
            'operations': len(self.batch_metrics),
            'total_tasks': total_tasks,
            'tasks_queued': total_queued,
            'tasks_failed': total_failed,
            'success_rate': (total_queued / total_tasks * 100) if total_tasks > 0 else 0,
            'total_time_ms': total_time,
            'avg_throughput_per_second': avg_throughput,
            'metrics': self.batch_metrics
        }

    # ========================================================================
    # Helper Methods
    # ========================================================================

    def _generate_correlation_id(self) -> str:
        """Generate correlation ID for tracking."""
        import uuid
        return str(uuid.uuid4())[:8]

    def _get_previous_stage_results(
        self,
        job_id: str,
        stage_number: int,
        task_repo: Any
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get results from previous stage tasks.

        Args:
            job_id: Job identifier
            stage_number: Previous stage number
            task_repo: Task repository instance

        Returns:
            List of previous stage results or None
        """
        try:
            tasks = task_repo.get_job_tasks(
                job_id,
                stage_filter=stage_number,
                status_filter=TaskStatus.COMPLETED
            )

            if tasks:
                return [t.get('result_data', {}) for t in tasks]

            return None

        except Exception as e:
            self.logger.warning(f"Failed to get previous stage results: {e}")
            return None


# ============================================================================
# CONCRETE IMPLEMENTATIONS
# ============================================================================

class ServiceBusHelloWorldController(ServiceBusBaseController):
    """
    Service Bus-optimized HelloWorld controller.

    Demonstrates batch processing with simple greeting/reply tasks.
    """

    REGISTRATION_INFO = {
        'job_type': 'sb_hello_world',
        'description': 'Service Bus HelloWorld with batch processing',
        'version': '1.0.0',
        'supported_parameters': ['n', 'message'],
        'stages': 2
    }

    def __init__(self):
        """Initialize Service Bus HelloWorld controller."""
        self._job_type = 'sb_hello_world'  # Set before calling super
        super().__init__()

    def get_job_type(self) -> str:
        """Return the job type identifier."""
        return self._job_type

    def validate_job_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Validate HelloWorld parameters."""
        validated = {}
        validated['n'] = max(1, min(1000, parameters.get('n', 3)))
        validated['message'] = parameters.get('message', 'Hello from Service Bus')
        validated['use_service_bus'] = True  # Force Service Bus usage
        return validated

    def create_stage_tasks(
        self,
        stage_number: int,
        job_id: str,
        job_parameters: Dict[str, Any],
        previous_stage_results: Optional[Dict[str, Any]] = None
    ) -> List[TaskDefinition]:
        """Create HelloWorld tasks for the stage."""
        n = job_parameters.get('n', 3)
        message = job_parameters.get('message', 'Hello')

        tasks = []

        if stage_number == 1:
            # Stage 1: Create greeting tasks
            for i in range(n):
                task_def = TaskDefinition(
                    task_id=f"{job_id}-s{stage_number}-greeting_{i}",
                    job_id=job_id,
                    job_type='hello_world',
                    task_type='hello_world_greeting',
                    stage_number=stage_number,
                    parameters={
                        'index': i,
                        'name': f"User_{i}",
                        'message': message
                    }
                )
                tasks.append(task_def)

        elif stage_number == 2:
            # Stage 2: Create reply tasks
            for i in range(n):
                task_def = TaskDefinition(
                    task_id=f"{job_id}-s{stage_number}-reply_{i}",
                    job_id=job_id,
                    job_type='hello_world',
                    task_type='hello_world_reply',
                    stage_number=stage_number,
                    parameters={
                        'index': i,
                        'greeting': f"Hello User_{i}"
                    }
                )
                tasks.append(task_def)

        return tasks

    def should_advance_stage(
        self,
        job_id: str,
        current_stage: int,
        stage_results: Dict[str, Any]
    ) -> bool:
        """Determine if job should advance to next stage."""
        return current_stage < 2  # Two-stage workflow

    def aggregate_stage_results(
        self,
        job_id: str,
        stage_number: int,
        task_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Aggregate results from stage tasks."""
        return {
            'stage': stage_number,
            'task_count': len(task_results),
            'processing_path': self.processing_path,
            'performance': self.get_performance_summary()
        }

    def aggregate_job_results(self, context) -> Dict[str, Any]:
        """
        Aggregate results from all stages into final job result.

        Args:
            context: JobExecutionContext with job data

        Returns:
            Final aggregated results for the job
        """
        # Get stage results from context
        stage_results = context.stage_results if hasattr(context, 'stage_results') else {}

        # Count tasks from each stage
        stage1_tasks = stage_results.get('1', {}).get('task_count', 0)
        stage2_tasks = stage_results.get('2', {}).get('task_count', 0)

        return {
            'job_type': self._job_type,
            'processing_path': self.processing_path,
            'stages_completed': 2,
            'total_tasks': stage1_tasks + stage2_tasks,
            'stage_results': stage_results,
            'performance_summary': self.get_performance_summary(),
            'message': f"HelloWorld job completed with {stage1_tasks + stage2_tasks} tasks via Service Bus"
        }