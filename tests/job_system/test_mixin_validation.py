"""
JobBaseMixin.validate_job_parameters() tests using HelloWorldJob.

Tests schema-based validation: defaults, type checking,
range validation, and required fields.
"""

import pytest
from unittest.mock import patch, MagicMock

from jobs.hello_world import HelloWorldJob


def _validate(params: dict) -> dict:
    """
    Call HelloWorldJob.validate_job_parameters with mocked system params.

    The mixin imports util_logger and core.schema.system_params at runtime.
    We mock those to avoid infrastructure dependencies.
    """
    mock_logger = MagicMock()
    mock_logger.debug = MagicMock()
    mock_logger.info = MagicMock()

    with patch("jobs.mixins.LoggerFactory", create=True) as mock_lf, \
         patch("jobs.mixins.validate_system_params", create=True, return_value={}):
        # The imports are inside the method, so we patch the import targets
        import jobs.mixins
        original_validate = jobs.mixins.JobBaseMixin.validate_job_parameters

        # Patch the internal imports
        with patch("util_logger.LoggerFactory") as mock_lf2, \
             patch("core.schema.system_params.validate_system_params", return_value={}):
            mock_lf2.create_logger.return_value = mock_logger
            return HelloWorldJob.validate_job_parameters(params)


class TestMixinValidation:

    def test_defaults_applied_when_empty_params(self):
        result = _validate({})
        assert result["n"] == 3
        assert result["message"] == "Hello World"
        assert result["failure_rate"] == 0.0

    def test_custom_values_accepted(self):
        result = _validate({"n": 10, "message": "Custom", "failure_rate": 0.5})
        assert result["n"] == 10
        assert result["message"] == "Custom"
        assert result["failure_rate"] == 0.5

    def test_partial_params_fills_defaults(self):
        result = _validate({"n": 7})
        assert result["n"] == 7
        assert result["message"] == "Hello World"  # default
        assert result["failure_rate"] == 0.0  # default

    def test_type_mismatch_int_raises(self):
        with pytest.raises(ValueError, match="integer"):
            _validate({"n": "not_an_int"})

    def test_type_mismatch_float_raises(self):
        with pytest.raises(ValueError, match="number"):
            _validate({"failure_rate": "not_a_float"})

    def test_min_boundary_accepted(self):
        result = _validate({"n": 1})
        assert result["n"] == 1

    def test_below_min_rejected(self):
        with pytest.raises(ValueError, match=">="):
            _validate({"n": 0})

    def test_max_boundary_accepted(self):
        result = _validate({"n": 1000})
        assert result["n"] == 1000

    def test_above_max_rejected(self):
        with pytest.raises(ValueError, match="<="):
            _validate({"n": 1001})

    def test_float_min_boundary(self):
        result = _validate({"failure_rate": 0.0})
        assert result["failure_rate"] == 0.0

    def test_float_max_boundary(self):
        result = _validate({"failure_rate": 1.0})
        assert result["failure_rate"] == 1.0

    def test_float_above_max_rejected(self):
        with pytest.raises(ValueError, match="<="):
            _validate({"failure_rate": 1.1})
