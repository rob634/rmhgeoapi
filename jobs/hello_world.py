"""
HelloWorld Job Declaration - Pure Data (No Decorators!)

This file declares WHAT the HelloWorld job is, not HOW it executes.
Execution logic lives in services/service_hello_world.py.

Author: Robert and Geospatial Claude Legion
Date: 1 OCT 2025
Updated: 15 OCT 2025 - Phase 2: Migrated to JobBase ABC
"""

from typing import List, Dict, Any
import hashlib
import json

from jobs.base import JobBase


class HelloWorldJob(JobBase):
    """
    HelloWorld job declaration - two stages of greetings and replies.

    This is PURE DATA - no execution logic, no decorators, no magic!
    Just a simple class that describes the job.
    """

    # Job metadata
    job_type: str = "hello_world"
    description: str = "Simple two-stage greeting workflow for testing"

    # Stage definitions (pure data!)
    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "greeting",
            "task_type": "hello_world_greeting",
            "parallelism": "dynamic",  # Creates n tasks based on params
            "count_param": "n"         # Which parameter controls count
        },
        {
            "number": 2,
            "name": "reply",
            "task_type": "hello_world_reply",
            "parallelism": "match_previous",  # Same count as stage 1
            "depends_on": 1,
            "uses_lineage": True  # Can access stage 1 results
        }
    ]

    # Parameter schema
    parameters_schema: Dict[str, Any] = {
        "n": {"type": "int", "min": 1, "max": 1000, "default": 3},
        "message": {"type": "str", "default": "Hello World"},
        "failure_rate": {"type": "float", "min": 0.0, "max": 1.0, "default": 0.0}
    }

    @staticmethod
    def create_tasks_for_stage(stage: int, job_params: dict, job_id: str, previous_results: list = None) -> List[dict]:
        """
        Generate task parameters for a stage.

        This is the ONLY job-specific logic - creating task parameters.
        Everything else (queuing, status updates, completion) is handled by CoreMachine.

        Args:
            stage: Stage number (1 or 2)
            job_params: Job parameters (n, message)
            job_id: Job ID for task ID generation

        Returns:
            List of task parameter dicts
        """
        n = job_params.get('n', 3)
        message = job_params.get('message', 'Hello World')

        if stage == 1:
            # Stage 1: Create greeting tasks with optional failure_rate
            failure_rate = job_params.get('failure_rate', 0.0)
            return [
                {
                    "task_id": f"{job_id[:8]}-s1-{i}",
                    "task_type": "hello_world_greeting",
                    "parameters": {
                        "index": i,
                        "message": message,
                        "failure_rate": failure_rate
                    }
                }
                for i in range(n)
            ]
        elif stage == 2:
            # Stage 2: Create reply tasks (matches stage 1 count)
            return [
                {
                    "task_id": f"{job_id[:8]}-s2-{i}",
                    "task_type": "hello_world_reply",
                    "parameters": {"index": i}
                }
                for i in range(n)
            ]
        else:
            return []

    @staticmethod
    def validate_job_parameters(params: dict) -> dict:
        """
        Validate job parameters against schema.

        Args:
            params: Raw parameters from request

        Returns:
            Validated parameters with defaults applied

        Raises:
            ValueError: If parameters are invalid
        """
        validated = {}

        # Validate 'n' parameter
        n = params.get('n', 3)
        if not isinstance(n, int):
            try:
                n = int(n)
            except (ValueError, TypeError):
                raise ValueError(f"Parameter 'n' must be an integer, got {type(n).__name__}")

        if n < 1 or n > 1000:
            raise ValueError(f"Parameter 'n' must be between 1 and 1000, got {n}")

        validated['n'] = n

        # Validate 'message' parameter
        message = params.get('message', 'Hello World')
        if not isinstance(message, str):
            raise ValueError(f"Parameter 'message' must be a string, got {type(message).__name__}")

        validated['message'] = message

        # Validate 'failure_rate' parameter (optional, for testing)
        failure_rate = params.get('failure_rate', 0.0)
        if not isinstance(failure_rate, (int, float)):
            raise ValueError(f"Parameter 'failure_rate' must be a number, got {type(failure_rate).__name__}")

        failure_rate = float(failure_rate)
        if failure_rate < 0.0 or failure_rate > 1.0:
            raise ValueError(f"Parameter 'failure_rate' must be between 0.0 and 1.0, got {failure_rate}")

        validated['failure_rate'] = failure_rate

        return validated

    @staticmethod
    def generate_job_id(params: dict) -> str:
        """
        Generate deterministic job ID from parameters.

        Args:
            params: Validated job parameters

        Returns:
            SHA256 hash as hex string
        """
        # Create deterministic string from job type and parameters
        # NOTE: failure_rate NOT included in job_id hash (it's for testing, not identity)
        job_type = "hello_world"
        canonical = json.dumps({
            "job_type": job_type,
            "n": params.get('n', 3),
            "message": params.get('message', 'Hello World')
        }, sort_keys=True)

        # Generate SHA256 hash
        hash_obj = hashlib.sha256(canonical.encode('utf-8'))
        return hash_obj.hexdigest()

    @staticmethod
    def create_job_record(job_id: str, params: dict) -> dict:
        """
        Create job record for database storage.

        Args:
            job_id: Generated job ID
            params: Validated parameters

        Returns:
            Job record dict
        """
        from infrastructure import RepositoryFactory
        from core.models import JobRecord, JobStatus

        # Create job record object
        job_record = JobRecord(
            job_id=job_id,
            job_type="hello_world",
            parameters=params,
            status=JobStatus.QUEUED,
            stage=1,
            total_stages=2,
            stage_results={},
            metadata={
                "description": "Simple two-stage greeting workflow",
                "created_by": "HelloWorldJob"
            }
        )

        # Persist to database
        repos = RepositoryFactory.create_repositories()
        job_repo = repos['job_repo']
        job_repo.create_job(job_record)

        # Return as dict
        return job_record.model_dump()

    @staticmethod
    def queue_job(job_id: str, params: dict) -> dict:
        """
        Queue job for processing using Service Bus.

        This is a SERVICE BUS ONLY application. Storage Queues are NOT supported.

        Args:
            job_id: Job ID
            params: Validated parameters

        Returns:
            Queue result information
        """
        from infrastructure.service_bus import ServiceBusRepository
        from core.schema.queue import JobQueueMessage
        from config import get_config
        from util_logger import LoggerFactory, ComponentType
        import uuid

        logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "HelloWorldJob.queue_job")

        logger.info(f"🚀 STEP 1: Starting queue_job for job_id={job_id}")
        logger.debug(f"   Parameters: {params}")

        # Get config for queue name
        try:
            logger.debug("📋 STEP 2: Loading configuration...")
            config = get_config()
            queue_name = config.service_bus_jobs_queue
            logger.info(f"✅ STEP 2: Config loaded - queue_name={queue_name}")
        except Exception as e:
            logger.error(f"❌ STEP 2 FAILED: Config loading error: {e}")
            raise

        # Create Service Bus repository
        try:
            logger.debug("🚌 STEP 3: Creating ServiceBusRepository...")
            service_bus_repo = ServiceBusRepository()
            logger.info(f"✅ STEP 3: ServiceBusRepository created")
        except Exception as e:
            logger.error(f"❌ STEP 3 FAILED: ServiceBusRepository creation error: {e}")
            raise

        # Create job queue message
        try:
            correlation_id = str(uuid.uuid4())
            logger.debug(f"📨 STEP 4: Creating JobQueueMessage with correlation_id={correlation_id}")
            job_message = JobQueueMessage(
                job_id=job_id,
                job_type="hello_world",
                stage=1,
                parameters=params,
                correlation_id=correlation_id
            )
            logger.info(f"✅ STEP 4: JobQueueMessage created - job_type=hello_world, stage=1")
        except Exception as e:
            logger.error(f"❌ STEP 4 FAILED: JobQueueMessage creation error: {e}")
            raise

        # Send to Service Bus jobs queue
        try:
            logger.debug(f"📤 STEP 5: Sending message to Service Bus queue: {queue_name}")
            message_id = service_bus_repo.send_message(queue_name, job_message)
            logger.info(f"✅ STEP 5: Message sent successfully - message_id={message_id}")
        except Exception as e:
            logger.error(f"❌ STEP 5 FAILED: Service Bus send error: {e}")
            raise

        result = {
            "queued": True,
            "queue_type": "service_bus",
            "queue_name": queue_name,
            "message_id": message_id,
            "job_id": job_id
        }

        logger.info(f"🎉 SUCCESS: Job queued successfully - {result}")
        return result
