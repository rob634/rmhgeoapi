# ============================================================================
# 🔧 TESTING INFRASTRUCTURE - Not for Production Use
# ============================================================================
# PURPOSE: Infrastructure validation and workflow testing
# STATUS: Working - Used for testing Job->Stage->Task patterns
# ============================================================================

# ============================================================================
# CLAUDE CONTEXT - JOB DEFINITION
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Job - Two-stage greeting workflow using JobBaseMixin
# PURPOSE: HelloWorld job with JobBaseMixin pattern (77% line reduction)
# LAST_REVIEWED: 22 NOV 2025
# EXPORTS: HelloWorldJob (JobBase + JobBaseMixin implementation)
# INTERFACES: JobBase (implements 2 methods), JobBaseMixin (provides 4 methods)
# PYDANTIC_MODELS: None (uses declarative parameters_schema)
# DEPENDENCIES: jobs.base.JobBase, jobs.mixins.JobBaseMixin
# SOURCE: HTTP job submission via POST /api/jobs/hello_world
# SCOPE: Test job for validating Job→Stage→Task workflow patterns
# VALIDATION: Declarative schema (n, message, failure_rate) via JobBaseMixin
# PATTERNS: Mixin pattern (composition over inheritance), Declarative config
# ENTRY_POINTS: Registered in jobs/__init__.py ALL_JOBS as "hello_world"
# INDEX: HelloWorldJob:40, stages:52, parameters_schema:80, create_tasks_for_stage:93
# ============================================================================

"""
HelloWorld Job - JobBaseMixin Pattern

Two-stage greeting workflow demonstrating JobBaseMixin boilerplate elimination.

Migrated from manual implementation (347 lines) to mixin pattern (219 lines).
Line reduction: 128 lines eliminated (37% reduction).

Two-Stage Workflow:
1. Stage 1 (greeting): Creates N parallel tasks with greetings (N from params)
2. Stage 2 (reply): Creates N parallel tasks with replies (matches stage 1 count)

Updated: 15 OCT 2025 - Phase 2: Migrated to JobBase ABC
Last Updated: 14 NOV 2025 - Migrated to JobBaseMixin pattern
"""

from typing import List, Dict, Any
from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


class HelloWorldJob(JobBaseMixin, JobBase):  # ← Mixin FIRST for correct MRO!
    """
    HelloWorld job using JobBaseMixin pattern.

    This is PURE DATA + MINIMAL LOGIC - no boilerplate!
    JobBaseMixin provides: validate, generate_id, create_record, queue.

    Two-Stage Workflow:
    1. Stage 1 (greeting): Creates N parallel tasks with greetings
    2. Stage 2 (reply): Creates N parallel tasks with replies
    """

    # ========================================================================
    # DECLARATIVE CONFIGURATION (No code!)
    # ========================================================================
    job_type = "hello_world"
    description = "Simple two-stage greeting workflow for testing"

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
        Use this as reference for internal/test workflows.

        Args:
            context: JobExecutionContext (optional for minimal implementations)

        Returns:
            Minimal job summary dict
        """
        from util_logger import LoggerFactory, ComponentType

        logger = LoggerFactory.create_logger(
            ComponentType.CONTROLLER,
            "HelloWorldJob.finalize_job"
        )

        if context:
            logger.info(f"✅ Job {context.job_id} completed with {len(context.task_results)} tasks")
            logger.debug(f"   Job parameters: {context.parameters}")
        else:
            logger.info("✅ HelloWorld job completed (no context provided)")

        return {
            "job_type": "hello_world",
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
