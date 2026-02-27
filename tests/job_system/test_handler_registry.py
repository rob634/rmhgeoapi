"""
Handler registry tests — ALL_HANDLERS, get_handler().

Cross-validates that every job stage has a matching handler.
"""

import pytest

from services import ALL_HANDLERS, get_handler
from jobs import ALL_JOBS


class TestHandlerRegistry:

    def test_registry_is_non_empty(self):
        assert len(ALL_HANDLERS) > 0

    def test_every_handler_is_callable(self):
        for task_type, handler in ALL_HANDLERS.items():
            assert callable(handler), f"Handler '{task_type}' is not callable"

    def test_get_unknown_handler_raises(self):
        with pytest.raises(ValueError, match="Unknown task type"):
            get_handler("nonexistent_handler_xyz")

    def test_get_known_handler_returns_callable(self):
        handler = get_handler("hello_world_greeting")
        assert callable(handler)

    def test_no_duplicate_handler_keys(self):
        """Registry keys should be unique (dict enforces this, but verify count)."""
        keys = list(ALL_HANDLERS.keys())
        assert len(keys) == len(set(keys))

    def test_every_job_stage_has_matching_handler(self):
        """
        Cross-validate: every task_type referenced in job stages
        must have a corresponding handler registered.
        """
        missing = []
        for job_type, job_class in ALL_JOBS.items():
            for stage in job_class.stages:
                task_type = stage.get("task_type")
                if task_type and task_type not in ALL_HANDLERS:
                    missing.append(f"{job_type}.{stage['name']}: {task_type}")

        assert not missing, (
            f"Job stages reference unregistered handlers: {missing}"
        )

    def test_hello_world_handlers_registered(self):
        assert "hello_world_greeting" in ALL_HANDLERS
        assert "hello_world_reply" in ALL_HANDLERS
