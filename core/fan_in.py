# ============================================================================
# FAN-IN HELPER - Database Reference Pattern for Aggregation Tasks
# ============================================================================
# CREATED: 05 JAN 2026
# PURPOSE: Load previous stage results from database for fan-in handlers
# PATTERN: CoreMachine passes reference, handler queries DB directly
# ============================================================================
"""
Fan-In Helper Module.

Provides utilities for fan-in handlers to load previous stage results from
the database. This implements the Database Reference Pattern introduced to
avoid the Service Bus 256KB message limit.

PATTERN (05 JAN 2026):
    CoreMachine no longer embeds previous_results in fan-in task parameters.
    Instead, it passes a reference (job_id + source_stage) and handlers
    query the database directly using this module.

Usage:
    from core.fan_in import load_fan_in_results

    def my_aggregation_handler(params, context):
        # Load results from database using the reference
        results = load_fan_in_results(params)

        # Process results
        for result in results:
            process(result)

Exports:
    load_fan_in_results: Load previous stage results from database
"""

from typing import Any
import logging

logger = logging.getLogger(__name__)


def load_fan_in_results(params: dict) -> list[dict]:
    """
    Load previous stage results from database for fan-in aggregation.

    This function retrieves completed task results from the database using
    the reference passed by CoreMachine in fan_in_source.

    Args:
        params: Task parameters containing fan_in_source reference:
            {
                "fan_in_source": {
                    "job_id": "abc123...",
                    "source_stage": 2,
                    "expected_count": 1924
                },
                "job_parameters": {...},
                "aggregation_metadata": {...}
            }

    Returns:
        List of result dicts from completed tasks in the source stage.
        Each dict is the task's result_data.get("result", result_data).

    Raises:
        KeyError: If params missing fan_in_source
        ValueError: If result count doesn't match expected (warning only)

    Example:
        >>> params = {"fan_in_source": {"job_id": "abc", "source_stage": 2, "expected_count": 100}}
        >>> results = load_fan_in_results(params)
        >>> len(results)
        100
    """
    from infrastructure.jobs_tasks import TaskRepository

    if "fan_in_source" not in params:
        raise KeyError(
            "Fan-in task missing 'fan_in_source' in parameters. "
            "This handler requires the database reference pattern. "
            "Ensure CoreMachine is using _create_fan_in_task() correctly."
        )

    source = params["fan_in_source"]
    job_id = source["job_id"]
    source_stage = source["source_stage"]
    expected_count = source.get("expected_count", 0)

    logger.info(
        f"📊 Loading fan-in results: job={job_id[:16]}..., "
        f"stage={source_stage}, expected={expected_count}"
    )

    # Query database for completed tasks from source stage
    task_repo = TaskRepository()
    tasks = task_repo.get_tasks_for_job(job_id)

    # Filter for completed tasks in the source stage with results
    results = []
    for task in tasks:
        if (task.stage == source_stage
            and task.status.value == "completed"
            and task.result_data):
            # Return full result_data (includes "success" field and nested "result")
            # Handlers expect: {"success": True, "result": {...}}
            # FIX (13 JAN 2026): Was extracting inner "result", breaking downstream handlers
            results.append(task.result_data)

    logger.info(f"   Retrieved {len(results)} results from database")

    # Validation warning (don't fail - counts might differ due to skipped tasks)
    if expected_count and len(results) != expected_count:
        logger.warning(
            f"   ⚠️ Result count mismatch: expected {expected_count}, got {len(results)}. "
            f"This may be normal if some tasks were skipped or had empty results."
        )

    return results


def get_fan_in_metadata(params: dict) -> dict:
    """
    Extract aggregation metadata from fan-in task parameters.

    Args:
        params: Task parameters

    Returns:
        Aggregation metadata dict with stage info, or empty dict if not present
    """
    return params.get("aggregation_metadata", {})


def get_job_parameters(params: dict) -> dict:
    """
    Extract original job parameters from fan-in task parameters.

    Args:
        params: Task parameters

    Returns:
        Original job parameters dict
    """
    return params.get("job_parameters", {})
