"""Tests for _eval_branch_condition edge cases — COMPETE Run 53 H3/L2."""
import pytest
from core.dag_fan_engine import _eval_branch_condition


class TestBranchConditionTypeErrors:
    """H3: in/not_in/contains/not_contains crash on non-iterable values."""

    def test_in_with_int_operand(self):
        """'in' operator with non-iterable operand should return False, not crash."""
        assert _eval_branch_condition("in 99", 42) is False

    def test_not_in_with_int_operand(self):
        assert _eval_branch_condition("not_in 99", 42) is False

    def test_contains_with_int_value(self):
        """'contains' operator with non-iterable value should return False."""
        assert _eval_branch_condition("contains 4", 42) is False

    def test_not_contains_with_int_value(self):
        assert _eval_branch_condition("not_contains 4", 42) is False

    def test_contains_with_none_value(self):
        assert _eval_branch_condition("contains foo", None) is False

    def test_in_with_none_operand(self):
        assert _eval_branch_condition("in None", "foo") is False

    def test_in_with_list_operand_works(self):
        """Normal case: 'in' with list should still work."""
        assert _eval_branch_condition('in ["a", "b"]', "a") is True

    def test_contains_with_string_value_works(self):
        """Normal case: 'contains' with string should still work."""
        assert _eval_branch_condition("contains hello", "hello world") is True
