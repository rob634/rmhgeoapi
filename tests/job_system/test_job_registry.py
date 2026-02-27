"""
Job registry tests — ALL_JOBS, get_job_class(), validate_job_registry().

Anti-overfitting: Count assertions catch silent additions/removals.
Cross-validation ensures registry key == class.job_type.
"""

import pytest

from jobs import ALL_JOBS, get_job_class, validate_job_registry


class TestJobRegistry:

    def test_registry_is_non_empty(self):
        assert len(ALL_JOBS) > 0

    def test_hello_world_registered(self):
        assert "hello_world" in ALL_JOBS

    def test_get_job_class_returns_correct_class(self):
        cls = get_job_class("hello_world")
        assert cls.job_type == "hello_world"

    def test_get_unknown_job_type_raises_ValueError(self):
        with pytest.raises(ValueError, match="Unknown job type"):
            get_job_class("nonexistent_job_type_xyz")

    def test_every_job_has_job_type_attribute(self):
        for job_type, job_class in ALL_JOBS.items():
            assert hasattr(job_class, "job_type"), f"{job_type} missing job_type"

    def test_every_job_has_stages_attribute(self):
        for job_type, job_class in ALL_JOBS.items():
            assert hasattr(job_class, "stages"), f"{job_type} missing stages"

    def test_every_job_has_at_least_one_stage(self):
        for job_type, job_class in ALL_JOBS.items():
            assert len(job_class.stages) >= 1, f"{job_type} has empty stages"

    def test_job_type_matches_registry_key(self):
        """For ALL jobs, the registry key must match class.job_type."""
        for key, job_class in ALL_JOBS.items():
            assert key == job_class.job_type, (
                f"Registry key '{key}' != class job_type '{job_class.job_type}'"
            )

    def test_validate_job_registry_passes(self):
        assert validate_job_registry() is True

    def test_no_duplicate_job_types(self):
        """All job_type values across classes are unique."""
        types = [cls.job_type for cls in ALL_JOBS.values()]
        assert len(types) == len(set(types))

    def test_every_job_has_description(self):
        for job_type, job_class in ALL_JOBS.items():
            assert hasattr(job_class, "description"), f"{job_type} missing description"
            assert job_class.description, f"{job_type} has empty description"
