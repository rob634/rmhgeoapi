# ============================================================================
# CLAUDE CONTEXT - JOB DEFINITION (MIXIN TEST VERSION)
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Job - Two-stage greeting workflow using JobBaseMixin (TEST VERSION)
# PURPOSE: Test JobBaseMixin pattern before migrating hello_world.py
# LAST_REVIEWED: 14 NOV 2025
# EXPORTS: HelloWorldMixinJob (JobBase + JobBaseMixin implementation)
# INTERFACES: JobBase (implements 2 methods), JobBaseMixin (provides 4 methods)
# PYDANTIC_MODELS: None (uses declarative parameters_schema)
# DEPENDENCIES: jobs.base.JobBase, jobs.mixins.JobBaseMixin
# SOURCE: HTTP job submission via POST /api/jobs/hello_world_mixin
# SCOPE: Test job for validating JobBaseMixin pattern (77% line reduction)
# VALIDATION: Declarative schema (n, message, failure_rate) via JobBaseMixin
# PATTERNS: Mixin pattern (composition over inheritance), Declarative config
# ENTRY_POINTS: Registered in jobs/__init__.py ALL_JOBS as "hello_world_mixin"
# INDEX: HelloWorldMixinJob:32, stages:44, parameters_schema:72, create_tasks_for_stage:85
# ============================================================================

"""
HelloWorld Job - JobBaseMixin Pattern Test Version

This is a TEST VERSION of hello_world.py using JobBaseMixin.
If successful, this will replace the original hello_world.py.

Demonstrates 77% line reduction:
- Before (hello_world.py): 347 lines
- After (this file): 125 lines
- Eliminated: 4 boilerplate methods (validate, generate_id, create_record, queue)

"""

from typing import List, Dict, Any
from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


class HelloWorldMixinJob(JobBaseMixin, JobBase):
    """
    HelloWorld job using JobBaseMixin pattern.

    Two-Stage Workflow:
    1. Stage 1 (greeting): Creates N parallel tasks with greetings
    2. Stage 2 (reply): Creates N parallel tasks with replies
    """

    # ========================================================================
    # DECLARATIVE CONFIGURATION (No code!)
    # ========================================================================
    job_type = "hello_world_mixin"  # ← Different job_type for testing
    description = "Simple two-stage greeting workflow for testing (mixin version)"

    # Stage definitions (pure data!)
    stages = [
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

    # Declarative parameter validation (no code!)
    # JobBaseMixin handles ALL validation logic automatically
    parameters_schema = {
        "n": {
            "type": "int",
            "min": 1,
            "max": 1000,
            "default": 3
        },
        "message": {
            "type": "str",
            "default": "Hello World"
        },
        "failure_rate": {
            "type": "float",
            "min": 0.0,
            "max": 1.0,
            "default": 0.0
        }
    }

    # ========================================================================
    # JOB-SPECIFIC LOGIC ONLY: Task Creation (~40 lines)
    # ========================================================================
    @staticmethod
    def create_tasks_for_stage(
        stage: int,
        job_params: dict,
        job_id: str,
        previous_results: list = None
    ) -> List[dict]:
        """
        Generate task parameters for a stage.

        This is the ONLY job-specific logic - everything else provided by mixin.

        Args:
            stage: Stage number (1 or 2)
            job_params: Job parameters (n, message, failure_rate)
            job_id: Job ID for task ID generation
            previous_results: Results from previous stage (unused in this job)

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

    # ========================================================================
    # JOB-SPECIFIC LOGIC ONLY: Finalization (~20 lines)
    # ========================================================================
    @staticmethod
    def finalize_job(context=None) -> Dict[str, Any]:
        """
        Create final job summary.

        This is the MINIMAL PATTERN - simple logging and basic summary.

        Args:
            context: JobExecutionContext (optional for minimal implementations)

        Returns:
            Minimal job summary dict
        """
        from util_logger import LoggerFactory, ComponentType

        logger = LoggerFactory.create_logger(
            ComponentType.CONTROLLER,
            "HelloWorldMixinJob.finalize_job"
        )

        if context:
            logger.info(f"✅ Job {context.job_id} completed with {len(context.task_results)} tasks")
            logger.debug(f"   Job parameters: {context.parameters}")
        else:
            logger.info("✅ HelloWorldMixin job completed (no context provided)")

        return {
            "job_type": "hello_world_mixin",
            "status": "completed"
        }

    # ========================================================================
    # CUSTOM OVERRIDE: Exclude failure_rate from job ID hash
    # ========================================================================
    # NOTE: This demonstrates how to override mixin methods when needed.
    # The original hello_world.py excludes failure_rate from the job_id hash
    # because it's a testing parameter, not part of job identity.
    @classmethod
    def generate_job_id(cls, params: dict) -> str:
        """
        Generate deterministic job ID from parameters.

        Override: Excludes 'failure_rate' from hash (it's for testing, not identity).

        Args:
            params: Validated job parameters

        Returns:
            SHA256 hash as hex string
        """
        import hashlib
        import json

        # Exclude failure_rate from job_id hash
        hash_params = {k: v for k, v in params.items() if k != 'failure_rate'}

        # Create canonical representation
        canonical = json.dumps({
            'job_type': cls.job_type,
            **hash_params
        }, sort_keys=True)

        # Generate SHA256 hash
        hash_obj = hashlib.sha256(canonical.encode('utf-8'))
        return hash_obj.hexdigest()