"""
JobBaseMixin.generate_job_id() tests.

Property assertions: 64-char hex, deterministic, collision-resistant.
"""

import pytest
import re

from jobs.hello_world import HelloWorldJob
from jobs.mixins import JobBaseMixin


class TestMixinJobId:

    def test_result_is_64_char_hex(self):
        result = HelloWorldJob.generate_job_id({"n": 3, "message": "hello"})
        assert len(result) == 64
        assert re.match(r"^[0-9a-f]{64}$", result)

    def test_deterministic(self):
        params = {"n": 5, "message": "test"}
        a = HelloWorldJob.generate_job_id(params)
        b = HelloWorldJob.generate_job_id(params)
        assert a == b

    def test_different_params_different_id(self):
        id1 = HelloWorldJob.generate_job_id({"n": 3, "message": "hello"})
        id2 = HelloWorldJob.generate_job_id({"n": 5, "message": "hello"})
        id3 = HelloWorldJob.generate_job_id({"n": 3, "message": "world"})
        assert len({id1, id2, id3}) == 3

    def test_failure_rate_excluded_from_hash(self):
        """HelloWorldJob overrides generate_job_id to exclude failure_rate."""
        id1 = HelloWorldJob.generate_job_id({"n": 3, "message": "hi", "failure_rate": 0.0})
        id2 = HelloWorldJob.generate_job_id({"n": 3, "message": "hi", "failure_rate": 0.5})
        assert id1 == id2

    def test_param_order_independent(self):
        """JSON sort_keys ensures order independence."""
        id1 = HelloWorldJob.generate_job_id({"n": 1, "message": "a"})
        id2 = HelloWorldJob.generate_job_id({"message": "a", "n": 1})
        assert id1 == id2

    def test_default_mixin_includes_job_type_in_hash(self):
        """
        The default mixin hash includes job_type. Two different job types
        with the same params should produce different IDs.

        We test this by calling the parent class method directly.
        """
        # Create two mock job classes with different job_types
        class JobA(JobBaseMixin):
            job_type = "job_type_a"
            parameters_schema = {}
            stages = []
            description = "A"

        class JobB(JobBaseMixin):
            job_type = "job_type_b"
            parameters_schema = {}
            stages = []
            description = "B"

        params = {"x": 1}
        # Call parent generate_job_id (not HelloWorldJob's override)
        id_a = JobBaseMixin.generate_job_id.__func__(JobA, params)
        id_b = JobBaseMixin.generate_job_id.__func__(JobB, params)
        assert id_a != id_b
