# ============================================================================
# HELLO WORLD SERVICE HANDLERS
# ============================================================================
# STATUS: Service layer - Test/example task handlers
# PURPOSE: Provide pure business logic handlers for hello_world job testing
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: handle_greeting, handle_reply
# ============================================================================
"""
HelloWorld Service Handlers - Pure Business Logic (No Decorators!)

These are pure functions that execute task logic. No decorators, no registration magic.
Registration happens explicitly in services/__init__.py.

Handler functions are simple:
- Take params dict and optional context dict
- Execute business logic
- Return result dict

"""

from typing import Dict, Any, Optional
from datetime import datetime, timezone
import random


def handle_greeting(params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Handle greeting task - pure business logic with optional stochastic failures.

    This is a Stage 1 task - no predecessor data needed.

    Args:
        params: Task parameters dict
            - index (int): Task index number
            - message (str): Greeting message template
            - failure_rate (float): Probability of random failure (0.0-1.0, default 0.0)
        context: Optional context (not used in stage 1)

    Returns:
        Result dict with greeting data

    Raises:
        Exception: If stochastic failure is triggered (based on failure_rate)
    """
    try:
        index = params.get('index', 0)
        message = params.get('message', 'Hello World')
        failure_rate = params.get('failure_rate', 0.0)

        # STOCHASTIC FAILURE INJECTION (for testing retry mechanisms)
        if failure_rate > 0.0 and random.random() < failure_rate:
            raise Exception(
                f"💥 STOCHASTIC FAILURE - Task {index} randomly failed "
                f"(failure_rate={failure_rate:.1%}) to test retry mechanisms"
            )

        return {
            "success": True,
            "greeting": f"{message} from task {index}!",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "task_index": index,
            "failure_rate_tested": failure_rate
        }

    except Exception as e:
        # Re-raise so CoreMachine can catch and mark task as FAILED
        raise


def handle_generate_list(params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Generate a list of items for fan-out testing.

    Returns a list of dicts, each with an index and a message.
    Used by test_fan_out.yaml to exercise the fan_out/fan_in machinery.
    """
    message = params.get('message', 'item')
    count = params.get('item_count', 3)

    items = [
        {"index": i, "label": f"{message}-{i}"}
        for i in range(count)
    ]

    return {
        "success": True,
        "items": items,
        "count": count,
    }


def handle_reply(params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Handle reply task - uses lineage to access predecessor.

    This is a Stage 2 task - can access Stage 1 results via context.

    Args:
        params: Task parameters dict
            - index (int): Task index number
        context: Context dict (optional)
            - predecessor_result (dict): Stage 1 task result if available

    Returns:
        Result dict with reply data
    """
    index = params.get('index', 0)

    # Access predecessor result if context provided
    # In real implementation, CoreMachine will provide this
    predecessor_greeting = "unknown"
    if context and 'predecessor_result' in context:
        predecessor_greeting = context['predecessor_result'].get('greeting', 'unknown')

    return {
        "success": True,
        "reply": f"Replying to: {predecessor_greeting}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task_index": index,
        "predecessor_accessed": context is not None and 'predecessor_result' in context
    }
