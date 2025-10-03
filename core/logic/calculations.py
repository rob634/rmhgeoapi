# ============================================================================
# CLAUDE CONTEXT - CORE LOGIC - CALCULATIONS
# ============================================================================
# CATEGORY: BUSINESS LOGIC HELPERS
# PURPOSE: Shared utility functions for calculations and state transitions
# EPOCH: Shared by all epochs (business logic)# PURPOSE: Business calculations for jobs and tasks
# EXPORTS: Functions for calculating rates, percentages, counts
# INTERFACES: Operates on core.models data structures
# DEPENDENCIES: core.models
# SOURCE: Business logic extracted from schema_base.py
# SCOPE: Calculation logic
# VALIDATION: Mathematical operations
# PATTERNS: Pure functions
# ENTRY_POINTS: from core.logic.calculations import calculate_success_rate
# ============================================================================

"""
Business calculations for jobs and tasks.

This module contains calculation logic separated from the data models.
All functions are pure and operate on model data.
"""

from typing import List, Dict, Any, Optional

from ..models.context import StageExecutionContext
from ..models.results import TaskResult, StageResultContract
from ..models.enums import TaskStatus


def calculate_success_rate(successful: int, total: int) -> float:
    """
    Calculate success rate as a percentage.

    Args:
        successful: Number of successful items
        total: Total number of items

    Returns:
        Success rate between 0.0 and 1.0
    """
    if total == 0:
        return 0.0
    return successful / total


def calculate_completion_percentage(completed: int, total: int) -> float:
    """
    Calculate completion percentage.

    Args:
        completed: Number of completed items
        total: Total number of items

    Returns:
        Completion percentage between 0.0 and 100.0
    """
    if total == 0:
        return 0.0
    return (completed / total) * 100.0


def is_stage_complete(context: StageExecutionContext) -> bool:
    """
    Check if a stage is complete based on task counts.

    Args:
        context: Stage execution context

    Returns:
        True if all tasks are completed or failed
    """
    return (context.completed_tasks + context.failed_tasks) >= context.total_tasks


def stage_success_rate(context: StageExecutionContext) -> float:
    """
    Calculate stage success rate.

    Args:
        context: Stage execution context

    Returns:
        Success rate between 0.0 and 1.0
    """
    if context.total_tasks == 0:
        return 0.0
    return context.completed_tasks / context.total_tasks


def count_successful_tasks(task_results: List[TaskResult]) -> int:
    """
    Count successful tasks from results.

    Args:
        task_results: List of task results

    Returns:
        Number of successful tasks
    """
    return sum(1 for result in task_results
               if result.status == TaskStatus.COMPLETED)


def count_failed_tasks(task_results: List[TaskResult]) -> int:
    """
    Count failed tasks from results.

    Args:
        task_results: List of task results

    Returns:
        Number of failed tasks
    """
    return sum(1 for result in task_results
               if result.status == TaskStatus.FAILED)


def aggregate_task_results(task_results: List[TaskResult]) -> Dict[str, Any]:
    """
    Aggregate task results into summary statistics.

    Args:
        task_results: List of task results

    Returns:
        Dictionary with aggregated statistics
    """
    total = len(task_results)
    successful = count_successful_tasks(task_results)
    failed = count_failed_tasks(task_results)

    return {
        'total_tasks': total,
        'successful_tasks': successful,
        'failed_tasks': failed,
        'success_rate': calculate_success_rate(successful, total),
        'completion_percentage': calculate_completion_percentage(
            successful + failed, total
        ),
        'has_failures': failed > 0
    }


def needs_retry(result: StageResultContract) -> bool:
    """
    Check if a stage needs retry based on results.

    Args:
        result: Stage result contract

    Returns:
        True if stage has failures that could be retried
    """
    return result.failed_count > 0 and result.status != 'failed'


def all_tasks_succeeded(result: StageResultContract) -> bool:
    """
    Check if all tasks in a stage succeeded.

    Args:
        result: Stage result contract

    Returns:
        True if all tasks succeeded
    """
    return result.failed_count == 0 and result.successful_count == result.task_count


def get_error_summary(task_results: List[TaskResult]) -> Optional[List[str]]:
    """
    Extract error messages from task results.

    Args:
        task_results: List of task results

    Returns:
        List of unique error messages, or None if no errors
    """
    errors = []
    seen = set()

    for result in task_results:
        if result.error_message and result.error_message not in seen:
            errors.append(result.error_message)
            seen.add(result.error_message)

    return errors if errors else None