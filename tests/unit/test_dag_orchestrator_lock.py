"""Tests for advisory lock lifecycle — COMPETE Run 53 H1."""
from core.dag_orchestrator import _advisory_lock_id


class TestAdvisoryLockId:
    def test_deterministic(self):
        """Same run_id always produces same lock_id."""
        assert _advisory_lock_id("abc") == _advisory_lock_id("abc")

    def test_different_for_different_runs(self):
        assert _advisory_lock_id("run-a") != _advisory_lock_id("run-b")

    def test_non_negative(self):
        """Lock ID must be non-negative (PostgreSQL bigint)."""
        lock_id = _advisory_lock_id("test-run-12345")
        assert lock_id >= 0

    def test_fits_63_bits(self):
        lock_id = _advisory_lock_id("test-run-12345")
        assert lock_id <= 0x7FFFFFFFFFFFFFFF
