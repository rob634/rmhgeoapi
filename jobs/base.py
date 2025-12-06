"""
JobBase - Abstract base class for all jobs.

Enforces the 6-method interface contract that CoreMachine expects.
No implementations, no business logic, just method signatures.

This enables:
    - Fail-fast at import time (not at HTTP request)
    - IDE autocomplete and type hints
    - Clear contract documentation
    - No inheritance bloat (just signatures)

6-Method Interface Contract:
    1. validate_job_parameters(params: dict) -> dict
    2. generate_job_id(params: dict) -> str
    3. create_job_record(job_id: str, params: dict) -> JobRecord
    4. queue_job(job_id: str, params: dict) -> dict
    5. create_tasks_for_stage(stage, job_params, job_id, previous_results) -> List[dict]
    6. finalize_job(context=None) -> Dict[str, Any]

Exports:
    JobBase: Abstract base class (ABC)

Dependencies:
    abc: Abstract Base Class
    typing: Type hints
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any


class JobBase(ABC):
    """
    Abstract base class enforcing job interface contract.

    All jobs must implement these 6 static methods. This ABC does NOT
    provide implementations - jobs remain simple classes that compose
    their own dependencies as needed.

    Required class attributes:
        job_type (str): Unique job identifier
        description (str): Human-readable description
        stages (List[Dict[str, Any]]): Stage definitions as plain dicts
            Each stage dict must contain:
            - number (int): Stage number (1-based)
            - name (str): Stage name
            - task_type (str): Handler name from services registry
            - parallelism (str): One of "single", "fan_out", or "fan_in"
                * "single": Orchestration-time parallelism
                    - Job creates tasks BEFORE any execution
                    - N can be from params (n=10), calculation, or hardcoded (1 task)
                    - Example: n=10 from request, or always create 1 analysis task
                * "fan_out": Result-driven parallelism
                    - Job creates tasks FROM previous stage execution results
                    - N discovered at runtime (from previous_results data)
                    - Example: Stage 1 lists files, Stage 2 creates task per file
                * "fan_in": Auto-aggregation (CoreMachine handles)
                    - CoreMachine auto-creates 1 task (job does nothing)
                    - Task receives ALL previous results via params["previous_results"]
                    - Example: Stage 2 has N tasks, Stage 3 aggregates all N results

    Required methods:
        validate_job_parameters: Validate/normalize parameters
        generate_job_id: Generate deterministic job ID
        create_job_record: Create and persist JobRecord
        queue_job: Queue JobQueueMessage to Service Bus
        create_tasks_for_stage: Generate task parameter dicts
        finalize_job: Create final job summary after all stages complete

    Usage:
        class YourJob(JobBase):
            job_type = "your_job"
            description = "What this job does"
            stages = [{"number": 1, "name": "...", "task_type": "..."}]

            @staticmethod
            def validate_job_parameters(params: dict) -> dict:
                # Your implementation
                return params

            # ... implement other 5 methods

    Design Philosophy:
        This ABC enforces ONLY the interface (WHAT methods must exist).
        It does NOT enforce implementation (HOW methods work).
        Jobs remain free to compose dependencies as needed.

    Benefits:
        - Fail-fast: Missing methods caught at import time
        - IDE support: Autocomplete and type hints
        - Documentation: ABC serves as executable contract
        - Composition-friendly: No implementation inheritance
    """

    # Class attributes (not enforced by ABC, but validated by registry)
    job_type: str
    description: str
    stages: List[Dict[str, Any]]

    @staticmethod
    @abstractmethod
    def validate_job_parameters(params: dict) -> dict:
        """
        Validate and normalize job parameters.

        Called by: triggers/submit_job.py line 171

        This method is responsible for:
        - Validating parameter types and values
        - Applying default values
        - Normalizing parameter formats
        - Raising ValueError for invalid parameters

        Args:
            params: Raw parameters from job submission

        Returns:
            Validated parameters with defaults applied

        Raises:
            ValueError: If parameters are invalid

        Implementation Notes:
            - Use Pydantic models for complex validation (optional)
            - Compose custom validators as needed
            - Return dict (not Pydantic model) for consistency
            - Keep validation logic simple and focused

        Example:
            @staticmethod
            def validate_job_parameters(params: dict) -> dict:
                if 'required_param' not in params:
                    raise ValueError("required_param is required")
                return {
                    'required_param': params['required_param'],
                    'optional_param': params.get('optional_param', 'default')
                }
        """
        pass

    @staticmethod
    @abstractmethod
    def generate_job_id(params: dict) -> str:
        """
        Generate deterministic job ID for idempotency.

        Called by: triggers/submit_job.py line 175

        This method must return the SAME job ID for identical parameters,
        enabling automatic deduplication of duplicate job submissions.

        Args:
            params: Validated job parameters

        Returns:
            Deterministic job ID (typically SHA256 hash as hex string)

        Implementation Notes:
            - Use SHA256 hash of job_type + sorted params (recommended)
            - Include only parameters that affect job identity
            - Exclude transient parameters (timestamps, etc.)
            - Return consistent format (lowercase hex recommended)

        Example:
            @staticmethod
            def generate_job_id(params: dict) -> str:
                import hashlib, json
                id_str = f"job_type:{json.dumps(params, sort_keys=True)}"
                return hashlib.sha256(id_str.encode()).hexdigest()
        """
        pass

    @staticmethod
    @abstractmethod
    def create_job_record(job_id: str, params: dict) -> dict:
        """
        Create JobRecord and persist to database.

        Called by: triggers/submit_job.py line 220

        This method is responsible for:
        - Creating JobRecord Pydantic model
        - Persisting to app.jobs table via repository
        - Setting initial job status (QUEUED)
        - Returning job creation confirmation

        Args:
            job_id: Generated job ID
            params: Validated parameters

        Returns:
            Job creation result dict (typically {"job_id": ..., "status": "queued"})

        Implementation Notes:
            - Must use RepositoryFactory.create_repositories() for database access
            - Create JobRecord with status=JobStatus.QUEUED
            - Set stage=1 (first stage)
            - Set total_stages from len(stages)
            - Use try/except for database errors

        Example:
            @staticmethod
            def create_job_record(job_id: str, params: dict) -> dict:
                from infrastructure import RepositoryFactory
                from core.models import JobRecord, JobStatus

                job_record = JobRecord(
                    job_id=job_id,
                    job_type="your_job",
                    parameters=params,
                    status=JobStatus.QUEUED,
                    stage=1,
                    total_stages=2,
                    stage_results={},
                    metadata={"description": "..."}
                )

                repos = RepositoryFactory.create_repositories()
                repos['job_repo'].create_job(job_record)
                return {"job_id": job_id, "status": "queued"}
        """
        pass

    @staticmethod
    @abstractmethod
    def queue_job(job_id: str, params: dict) -> dict:
        """
        Queue JobQueueMessage to Service Bus.

        Called by: triggers/submit_job.py line 226

        This method is responsible for:
        - Creating JobQueueMessage Pydantic model
        - Sending to Service Bus 'jobs' queue
        - Triggering CoreMachine job processing
        - Returning queue confirmation

        Args:
            job_id: Job ID
            params: Validated parameters

        Returns:
            Queue result information dict

        Implementation Notes:
            - Must send to Service Bus (NOT Storage Queue)
            - Use ServiceBusRepository with jobs queue
            - Create JobQueueMessage with stage=1
            - Generate unique message_id and correlation_id
            - Use config.get_service_bus_connection()

        Example:
            @staticmethod
            def queue_job(job_id: str, params: dict) -> dict:
                from infrastructure.service_bus import ServiceBusRepository
                from core.schema.queue import JobQueueMessage
                from config import get_config
                import uuid

                message = JobQueueMessage(
                    job_id=job_id,
                    job_type="your_job",
                    stage=1,
                    parameters=params,
                    message_id=str(uuid.uuid4()),
                    correlation_id=str(uuid.uuid4())[:8]
                )

                config = get_config()
                service_bus = ServiceBusRepository(
                    connection_string=config.get_service_bus_connection(),
                    queue_name=config.jobs_queue_name
                )
                message_id = service_bus.send_message(message.model_dump_json())

                return {
                    "queued": True,
                    "queue_type": "service_bus",
                    "message_id": message_id
                }
        """
        pass

    @staticmethod
    @abstractmethod
    def create_tasks_for_stage(
        stage: int,
        job_params: dict,
        job_id: str,
        previous_results: list = None
    ) -> List[dict]:
        """
        Generate task parameter dicts for a stage.

        Called by: core/machine.py line 248

        This is the ONLY job-specific logic method - it defines WHAT tasks
        to create for each stage. CoreMachine handles HOW to execute them.

        Args:
            stage: Stage number (1-based, sequential)
            job_params: Job parameters from submission
            job_id: Job ID for task ID generation
            previous_results: Results from previous stage (for fan-out patterns)

        Returns:
            List of task parameter dicts, each containing:
            - task_id (str): Unique task identifier
            - task_type (str): Handler name from services registry
            - parameters (dict): Task-specific parameters
            - metadata (dict, optional): Additional task metadata

        Implementation Notes:
            - Return plain dicts (NOT Pydantic objects)
            - CoreMachine converts dicts → TaskDefinition Pydantic objects
            - Task IDs should be unique and meaningful
            - Recommended format: f"{job_id[:8]}-s{stage}-{index}"
            - Use previous_results for fan-out patterns (stage 2+ dynamic tasks)

        Example (Orchestration-Time Parallelism - "single"):
            # Stage definition: {"parallelism": "single"}
            # Tasks created BEFORE any execution (N from params or hardcoded)

            @staticmethod
            def create_tasks_for_stage(stage, job_params, job_id, previous_results=None):
                if stage == 1:
                    # Option A: N from job parameters
                    n = job_params.get('n', 3)
                    return [
                        {
                            "task_id": f"{job_id[:8]}-s1-{i}",
                            "task_type": "process_item",
                            "parameters": {"index": i, "data": job_params.get('data')}
                        }
                        for i in range(n)
                    ]

                    # Option B: Always 1 task (hardcoded)
                    # return [{
                    #     "task_id": f"{job_id[:8]}-s1-analyze",
                    #     "task_type": "analyze_raster",
                    #     "parameters": {"raster_path": job_params["raster"]}
                    # }]
                return []

        Example (Result-Driven Parallelism - "fan_out"):
            # Stage 1 definition: {"parallelism": "single"}
            # Stage 2 definition: {"parallelism": "fan_out"}
            # Stage 2 tasks created FROM Stage 1 execution results (N discovered at runtime)

            @staticmethod
            def create_tasks_for_stage(stage, job_params, job_id, previous_results=None):
                if stage == 1:
                    # Stage 1: Create 1 task (could also create N from params)
                    # This task EXECUTES and outputs a list of items
                    return [{
                        "task_id": f"{job_id[:8]}-s1-list",
                        "task_type": "list_container_files",
                        "parameters": {"container": job_params['container']}
                    }]

                elif stage == 2:
                    # Stage 2: Fan-out - Create tasks from Stage 1 results
                    # N is discovered at runtime (after Stage 1 execution completes)
                    if not previous_results:
                        raise ValueError("Stage 2 requires Stage 1 results")

                    # Extract file list from Stage 1 task result
                    file_list = previous_results[0]['result']['files']  # ← Runtime discovery

                    # Create one task per file
                    return [
                        {
                            "task_id": f"{job_id[:8]}-s2-{file_name}",
                            "task_type": "process_file",
                            "parameters": {"file_name": file_name}
                        }
                        for file_name in file_list
                    ]
                return []

        Example (Fan-In Stage - CoreMachine Auto-Creates Task):
            # Job declares stages with "fan_in" parallelism
            stages = [
                {"number": 1, "task_type": "list_files", "parallelism": "single"},
                {"number": 2, "task_type": "process_file", "parallelism": "fan_out"},
                {"number": 3, "task_type": "aggregate_results", "parallelism": "fan_in"}
            ]

            # Stage 3 is fan-in - CoreMachine automatically creates aggregation task
            # Job does NOT implement create_tasks_for_stage() for fan-in stages
            # Task handler receives ALL Stage 2 results via params["previous_results"]
        """
        pass

    @staticmethod
    @abstractmethod
    def finalize_job(context=None) -> Dict[str, Any]:
        """
        Create final job summary after all stages complete.

        Called by: core/machine.py (after last task completes final stage)

        This method is responsible for:
        - Creating user-facing job summary from completed task results
        - Extracting key outputs (STAC items, file paths, statistics)
        - Formatting results for Platform layer (if integrated)
        - Logging job completion

        This method is REQUIRED for ALL workflows. It enables:
        - Consistent job completion handling across all workflow types
        - Platform integration via on_job_complete callback (optional)
        - Standalone CoreMachine deployment ("system in a box")
        - Progressive enhancement (minimal → rich implementations)

        Args:
            context (JobExecutionContext, optional): Contains:
                - job_id (str): Job identifier
                - job_type (str): Workflow type
                - job_parameters (dict): Original job submission parameters
                - task_results (List[dict]): All completed task results
                - stage_results (dict): Aggregated results per stage

                If None, workflow should:
                - Log completion message
                - Return minimal summary (job_type, status)

        Returns:
            Dict[str, Any]: Job summary with minimum fields:
                - job_type (str): Workflow identifier
                - status (str): "completed" or "failed"

                Optional rich fields (workflow-specific):
                - job_id (str): Job identifier
                - total_tasks (int): Number of tasks executed
                - outputs (dict): Key outputs (STAC items, files, stats)
                - metadata (dict): Additional context
                - errors (list): Any non-fatal errors encountered

        Implementation Patterns:

        Pattern 1 - Minimal (Hello World, Internal Workflows):
            @staticmethod
            def finalize_job(context=None) -> Dict[str, Any]:
                '''Simple completion logging and minimal summary.'''
                logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "HelloWorldWorkflow.finalize_job")

                if context:
                    logger.info(f"Job {context.job_id} completed with {len(context.task_results)} tasks")
                else:
                    logger.info("Job completed (no context provided)")

                return {
                    "job_type": "hello_world",
                    "status": "completed"
                }

        Pattern 2 - Rich (User-Facing Workflows):
            @staticmethod
            def finalize_job(context) -> Dict[str, Any]:
                '''Extract and format key outputs for user/Platform.'''
                logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "ProcessRasterWorkflow.finalize_job")

                # Extract STAC item from Stage 3 results
                stac_results = [r for r in context.task_results if r.get('task_type') == 'create_stac_collection']
                stac_item_id = stac_results[0]['result']['stac_item_id'] if stac_results else None

                # Extract COG path from Stage 2 results
                cog_results = [r for r in context.task_results if r.get('task_type') == 'create_cog']
                cog_path = cog_results[0]['result']['output_blob'] if cog_results else None

                summary = {
                    "job_type": "process_raster",
                    "job_id": context.job_id,
                    "status": "completed",
                    "total_tasks": len(context.task_results),
                    "outputs": {
                        "stac_item_id": stac_item_id,
                        "cog_path": cog_path
                    },
                    "metadata": {
                        "source_blob": context.job_parameters.get("blob_name"),
                        "collection": context.job_parameters.get("collection_id")
                    }
                }

                logger.info(f"Job {context.job_id} finalized: {summary}")
                return summary

        Platform Integration (Automatic):
            If CoreMachine initialized with on_job_complete callback:
            1. finalize_job() creates summary dict
            2. CoreMachine stores summary in app.jobs.result_data
            3. CoreMachine invokes callback(job_id, job_type, status, summary)
            4. Platform layer receives summary and updates platform.api_requests

            If no callback (standalone deployment):
            1. finalize_job() creates summary dict
            2. CoreMachine stores summary in app.jobs.result_data
            3. No callback invoked (no Platform layer)

        Design Philosophy:
            - finalize_job() focuses on CREATING summary (data production)
            - Callback focuses on CONSUMING summary (Platform orchestration)
            - They are loosely coupled via dict interface
            - Enables "system in a box" deployment (CoreMachine alone)
            - Supports progressive enhancement (start minimal, add richness later)

        Fail-Fast Validation:
            - Missing finalize_job() = ImportError at application startup
            - No runtime surprises - contract enforced at import time
            - IDE autocomplete guides implementation

        Example Usage in CoreMachine:
            # Called after last task completes final stage
            workflow = self.jobs_registry[job_type]
            context = JobExecutionContext(
                job_id=job_id,
                job_type=job_type,
                job_parameters=job_params,
                task_results=all_task_results,
                stage_results=stage_results
            )
            summary = workflow.finalize_job(context)  # ← Required method

            # Store summary in database
            job_repo.update_job(job_id, result_data=summary, status="completed")

            # Invoke callback if present (Platform integration)
            if self.on_job_complete:
                self.on_job_complete(job_id, job_type, "completed", summary)
        """
        pass
