"""
Container List Job - Two-Stage Fan-Out Pattern.

Lists and analyzes blob container contents using fan-out parallelism.

Workflow:
    Stage 1: Lists all blobs in a container (single task)
    Stage 2: Analyzes each blob individually (fan-out - N tasks)

Results stored in task.result_data JSONB fields for SQL querying.

Exports:
    ListContainerContentsWorkflow: Two-stage container inventory job
"""

from typing import List, Dict, Any
import hashlib
import json

from jobs.base import JobBase


class ListContainerContentsWorkflow(JobBase):
    """
    Two-stage fan-out job for detailed container inventory.

    Stage 1: Single task lists all blobs in container
    Stage 2: N parallel tasks (one per blob) analyze and store metadata

    Results: Each blob's metadata stored in Stage 2 task.result_data
    """

    # Job metadata
    job_type: str = "list_container_contents"
    description: str = "Detailed file-by-file analysis of container contents"

    # Stage definitions
    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "list_blobs",
            "task_type": "list_container_blobs",
            "description": "Enumerate all blobs in container",
            "parallelism": "single"
        },
        {
            "number": 2,
            "name": "analyze_blobs",
            "task_type": "analyze_single_blob",
            "description": "Analyze individual blob metadata and store in task.result_data",
            "parallelism": "fan_out"
        }
    ]

    # Parameter schema
    parameters_schema: Dict[str, Any] = {
        "container_name": {"type": "str", "required": True},
        "file_limit": {"type": "int", "min": 1, "max": 10000, "default": None},
        "filter": {"type": "dict", "default": {}}
    }

    @staticmethod
    def validate_job_parameters(params: dict) -> dict:
        """
        Validate job parameters.

        Required:
            container_name: str - Azure storage container name

        Optional:
            file_limit: int - Max files to process (1-10000, default: None = all)
            filter: dict - Filter criteria (extensions, prefix, size, dates)

        Returns:
            Validated parameters dict

        Raises:
            ValueError: If parameters are invalid
        """
        validated = {}

        # Validate container_name (required)
        if "container_name" not in params:
            raise ValueError("container_name is required")

        container_name = params["container_name"]
        if not isinstance(container_name, str) or not container_name.strip():
            raise ValueError("container_name must be a non-empty string")

        validated["container_name"] = container_name.strip()

        # Validate file_limit (optional)
        file_limit = params.get("file_limit")
        if file_limit is not None:
            if not isinstance(file_limit, int):
                try:
                    file_limit = int(file_limit)
                except (ValueError, TypeError):
                    raise ValueError(f"file_limit must be an integer, got {type(file_limit).__name__}")

            if file_limit < 1 or file_limit > 10000:
                raise ValueError(f"file_limit must be between 1 and 10000, got {file_limit}")

            validated["file_limit"] = file_limit
        else:
            validated["file_limit"] = None

        # Validate filter (optional)
        filter_criteria = params.get("filter", {})
        if filter_criteria and not isinstance(filter_criteria, dict):
            raise ValueError("filter must be a dictionary")

        # Validate filter sub-fields
        if filter_criteria:
            if "prefix" in filter_criteria:
                if not isinstance(filter_criteria["prefix"], str):
                    raise ValueError("filter.prefix must be a string")

            if "extensions" in filter_criteria:
                if not isinstance(filter_criteria["extensions"], list):
                    raise ValueError("filter.extensions must be a list")

            for size_field in ["min_size_mb", "max_size_mb"]:
                if size_field in filter_criteria:
                    if not isinstance(filter_criteria[size_field], (int, float)):
                        raise ValueError(f"filter.{size_field} must be a number")

        validated["filter"] = filter_criteria

        # NOTE: Container existence check removed from validation to avoid timeouts
        # Container will be checked when Stage 1 task executes

        return validated

    @staticmethod
    def generate_job_id(params: dict) -> str:
        """
        Generate deterministic job ID from parameters.

        Same parameters = same job ID (idempotency).
        """
        # Sort keys for consistent hashing
        param_str = json.dumps(params, sort_keys=True)
        job_hash = hashlib.sha256(param_str.encode()).hexdigest()
        return job_hash

    @staticmethod
    def create_tasks_for_stage(stage: int, job_params: dict, job_id: str, previous_results: list = None) -> list[dict]:
        """
        Generate task parameters for a stage.

        Stage 1: Single task to list all blobs
        Stage 2: Fan-out - one task per blob from Stage 1 results

        Args:
            stage: Stage number (1 or 2)
            job_params: Job parameters
            job_id: Job ID for task ID generation
            previous_results: Results from Stage 1 (required for Stage 2)

        Returns:
            List of task parameter dicts

        Raises:
            ValueError: If Stage 2 called without previous_results
        """
        from core.task_id import generate_deterministic_task_id

        if stage == 1:
            # Stage 1: Single task to list blobs
            task_id = generate_deterministic_task_id(job_id, 1, "list")
            return [
                {
                    "task_id": task_id,
                    "task_type": "list_container_blobs",
                    "parameters": {
                        "container_name": job_params["container_name"],
                        "file_limit": job_params.get("file_limit"),
                        "filter": job_params.get("filter", {})
                    }
                }
            ]

        elif stage == 2:
            # Stage 2: FAN-OUT - Create one task per blob
            if not previous_results:
                raise ValueError("Stage 2 requires Stage 1 results for fan-out")

            # Extract blob names from Stage 1 result
            stage_1_result = previous_results[0]  # Single Stage 1 task
            if not stage_1_result.get('success'):
                raise ValueError(f"Stage 1 failed: {stage_1_result.get('error')}")

            blob_names = stage_1_result['result']['blob_names']

            # Create one task per blob with deterministic ID
            tasks = []
            for blob_name in blob_names:
                task_id = generate_deterministic_task_id(job_id, 2, blob_name)
                tasks.append({
                    "task_id": task_id,
                    "task_type": "analyze_single_blob",
                    "parameters": {
                        "container_name": job_params["container_name"],
                        "blob_name": blob_name
                    }
                })

            return tasks

        else:
            return []

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
            job_type="list_container_contents",
            parameters=params,
            status=JobStatus.QUEUED,
            stage=1,
            total_stages=2,
            stage_results={},
            metadata={
                "description": "Detailed file-by-file container inventory",
                "created_by": "ListContainerContentsWorkflow"
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

        logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "ListContainerContentsWorkflow.queue_job")

        logger.info(f"🚀 Starting queue_job for job_id={job_id}")

        # Get config for queue name
        config = get_config()
        queue_name = config.service_bus_jobs_queue

        # Create Service Bus repository
        service_bus_repo = ServiceBusRepository()

        # Create job queue message
        correlation_id = str(uuid.uuid4())[:8]
        job_message = JobQueueMessage(
            job_id=job_id,
            job_type="list_container_contents",
            stage=1,
            parameters=params,
            correlation_id=correlation_id
        )

        # Send to Service Bus jobs queue
        message_id = service_bus_repo.send_message(queue_name, job_message)
        logger.info(f"✅ Message sent successfully - message_id={message_id}")

        result = {
            "queued": True,
            "queue_type": "service_bus",
            "queue_name": queue_name,
            "message_id": message_id,
            "job_id": job_id
        }

        logger.info(f"🎉 Job queued successfully - {result}")
        return result

    @staticmethod
    def finalize_job(context) -> Dict[str, Any]:
        """
        Aggregate results from list + analyze tasks.

        This is critical for fan-out jobs - Stage 2 can create 1000+ parallel tasks.
        Without proper aggregation, you lose visibility into what was analyzed.

        Args:
            context: JobExecutionContext with task results

        Returns:
            Aggregated job results dict with comprehensive statistics
        """
        from core.models import TaskStatus
        from util_logger import LoggerFactory, ComponentType

        logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "ListContainerContentsWorkflow.finalize_job")

        try:
            logger.info("🔄 STEP 1: Starting result aggregation...")

            task_results = context.task_results
            params = context.parameters

            logger.info(f"   Total tasks: {len(task_results)}")
            logger.info(f"   Container: {params.get('container_name')}")

            # STEP 2: Separate tasks by stage
            try:
                logger.info("🔄 STEP 2: Separating tasks by stage...")
                list_tasks = [t for t in task_results if t.task_type == "list_container_blobs"]
                analyze_tasks = [t for t in task_results if t.task_type == "analyze_single_blob"]

                logger.info(f"   List tasks (Stage 1): {len(list_tasks)}")
                logger.info(f"   Analyze tasks (Stage 2): {len(analyze_tasks)}")

            except Exception as e:
                logger.error(f"❌ STEP 2 FAILED: Error separating tasks: {e}")
                raise

            # STEP 3: Extract Stage 1 results (total blobs found)
            total_blobs_found = 0
            try:
                logger.info("🔄 STEP 3: Extracting Stage 1 results...")

                if list_tasks and list_tasks[0].result_data:
                    stage_1_result = list_tasks[0].result_data.get("result", {})
                    blob_names = stage_1_result.get("blob_names", [])
                    total_blobs_found = len(blob_names)
                    logger.info(f"   Total blobs found in Stage 1: {total_blobs_found}")
                else:
                    logger.warning("   No Stage 1 results found (list task may have failed)")

            except Exception as e:
                logger.error(f"❌ STEP 3 FAILED: Error extracting Stage 1 results: {e}")
                # Don't raise - continue with Stage 2 aggregation
                total_blobs_found = 0

            # STEP 4: Count successful/failed analyses
            try:
                logger.info("🔄 STEP 4: Counting task statuses...")

                successful_analyses = sum(1 for t in analyze_tasks if t.status == TaskStatus.COMPLETED)
                failed_analyses = sum(1 for t in analyze_tasks if t.status == TaskStatus.FAILED)
                pending_analyses = sum(1 for t in analyze_tasks if t.status == TaskStatus.QUEUED)

                logger.info(f"   Successful: {successful_analyses}")
                logger.info(f"   Failed: {failed_analyses}")
                logger.info(f"   Pending: {pending_analyses}")

            except Exception as e:
                logger.error(f"❌ STEP 4 FAILED: Error counting statuses: {e}")
                successful_analyses = 0
                failed_analyses = 0
                pending_analyses = 0

            # STEP 5: Aggregate blob statistics
            total_size_bytes = 0
            file_types = {}
            largest_file = {"name": None, "size_mb": 0}
            errors_encountered = []

            try:
                logger.info("🔄 STEP 5: Aggregating blob statistics...")

                for i, task in enumerate(analyze_tasks):
                    try:
                        # Only aggregate completed tasks with result data
                        if task.status == TaskStatus.COMPLETED and task.result_data:
                            result = task.result_data.get("result", {})

                            # Aggregate size
                            try:
                                size_bytes = result.get("size_bytes", 0)
                                if isinstance(size_bytes, (int, float)) and size_bytes > 0:
                                    total_size_bytes += size_bytes
                            except Exception as e:
                                logger.debug(f"   Warning: Could not aggregate size for task {i}: {e}")

                            # Track largest file
                            try:
                                blob_name = result.get("blob_name", result.get("name"))
                                size_mb = size_bytes / (1024 * 1024) if size_bytes > 0 else 0

                                if size_mb > largest_file["size_mb"]:
                                    largest_file = {
                                        "name": blob_name,
                                        "size_mb": round(size_mb, 2)
                                    }
                            except Exception as e:
                                logger.debug(f"   Warning: Could not track largest file for task {i}: {e}")

                            # Count file types by extension
                            try:
                                blob_name = result.get("blob_name", result.get("name", ""))
                                if blob_name and isinstance(blob_name, str):
                                    extension = blob_name.split('.')[-1].lower() if '.' in blob_name else "no_extension"
                                    file_types[extension] = file_types.get(extension, 0) + 1
                            except Exception as e:
                                logger.debug(f"   Warning: Could not count file type for task {i}: {e}")

                        # Track failed tasks
                        elif task.status == TaskStatus.FAILED:
                            error_msg = task.result_data.get("error", "Unknown error") if task.result_data else "No error info"
                            errors_encountered.append({
                                "task_id": task.task_id[:16] + "..." if hasattr(task, 'task_id') else "unknown",
                                "error": error_msg
                            })

                    except Exception as e:
                        logger.debug(f"   Warning: Error processing task {i}: {e}")
                        continue

                logger.info(f"   Total size: {total_size_bytes / (1024**3):.2f} GB")
                logger.info(f"   File types: {len(file_types)} unique extensions")
                logger.info(f"   Largest file: {largest_file['name']} ({largest_file['size_mb']} MB)")

            except Exception as e:
                logger.error(f"❌ STEP 5 FAILED: Error aggregating statistics: {e}")
                # Continue with whatever we have

            # STEP 6: Build aggregated result
            try:
                logger.info("🔄 STEP 6: Building final result...")

                success_rate = f"{(successful_analyses / len(analyze_tasks) * 100):.1f}%" if analyze_tasks else "0%"

                result = {
                    "job_type": "list_container_contents",
                    "container_name": params.get("container_name"),
                    "file_limit": params.get("file_limit"),
                    "filter": params.get("filter", {}),
                    "summary": {
                        "total_blobs_found": total_blobs_found,
                        "blobs_analyzed": len(analyze_tasks),
                        "successful_analyses": successful_analyses,
                        "failed_analyses": failed_analyses,
                        "pending_analyses": pending_analyses,
                        "success_rate": success_rate,
                        "total_size_bytes": total_size_bytes,
                        "total_size_gb": round(total_size_bytes / (1024**3), 3),
                        "total_size_mb": round(total_size_bytes / (1024**2), 1),
                        "file_types": file_types,
                        "unique_extensions": len(file_types),
                        "largest_file": largest_file if largest_file["name"] else None,
                        "errors_sample": errors_encountered[:5] if errors_encountered else []  # First 5 errors
                    },
                    "stages_completed": context.current_stage,
                    "total_tasks_executed": len(task_results),
                    "tasks_by_status": {
                        "completed": sum(1 for t in task_results if t.status == TaskStatus.COMPLETED),
                        "failed": sum(1 for t in task_results if t.status == TaskStatus.FAILED),
                        "queued": sum(1 for t in task_results if t.status == TaskStatus.QUEUED)
                    }
                }

                logger.info("✅ STEP 6: Result built successfully")
                logger.info(f"🎉 Aggregation complete: {total_blobs_found} blobs found, {successful_analyses}/{len(analyze_tasks)} analyzed successfully")

                return result

            except Exception as e:
                logger.error(f"❌ STEP 6 FAILED: Error building result: {e}")
                # Return minimal result rather than failing
                return {
                    "job_type": "list_container_contents",
                    "container_name": params.get("container_name"),
                    "error": "Aggregation failed",
                    "error_details": str(e),
                    "total_tasks": len(task_results)
                }

        except Exception as e:
            logger.error(f"❌ CRITICAL: Aggregation failed completely: {e}")
            # Return minimal fallback result
            return {
                "job_type": "list_container_contents",
                "error": "Critical aggregation failure",
                "error_details": str(e),
                "fallback": True
            }
