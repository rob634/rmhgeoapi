# ============================================================================
# CIRCUIT BREAKER FOR DATABASE CONNECTIONS
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Infrastructure - Prevents cascade failures on DB outage
# PURPOSE: Fail fast when DB is down, auto-recover when it comes back
# LAST_REVIEWED: 13 MAR 2026
# EXPORTS: CircuitBreaker, CircuitBreakerState
# DEPENDENCIES: threading, time
# ============================================================================
"""
Circuit Breaker for Database Connections.

Prevents cascade failures when PostgreSQL is down or recovering (e.g., after OOM).

States:
    CLOSED  -> Normal operation. All requests go through.
    OPEN    -> DB is down. Fail fast for `recovery_timeout` seconds.
    HALF_OPEN -> Probe: allow ONE request through to test recovery.

Transitions:
    CLOSED -> OPEN: `failure_threshold` failures within `failure_window` seconds.
    OPEN -> HALF_OPEN: `recovery_timeout` seconds elapsed.
    HALF_OPEN -> CLOSED: Probe request succeeds.
    HALF_OPEN -> OPEN: Probe request fails (reset recovery timer).
"""

import time
import threading
import logging
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class CircuitBreakerState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


# Default configuration
DEFAULT_FAILURE_THRESHOLD = 3
DEFAULT_FAILURE_WINDOW = 10.0    # seconds — failures must occur within this window to trip
DEFAULT_RECOVERY_TIMEOUT = 30.0  # seconds — how long to stay OPEN before probing


class CircuitBreaker:
    """
    Thread-safe circuit breaker for database connections.

    Usage:
        breaker = CircuitBreaker.get_instance()

        # Before attempting DB connection:
        breaker.check()  # Raises CircuitBreakerOpenError if OPEN

        # After successful DB operation:
        breaker.record_success()

        # After failed DB operation:
        breaker.record_failure()

        # Get current state for monitoring:
        stats = breaker.get_stats()
    """

    _instance: Optional['CircuitBreaker'] = None
    _instance_lock = threading.Lock()

    def __init__(
        self,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        failure_window: float = DEFAULT_FAILURE_WINDOW,
        recovery_timeout: float = DEFAULT_RECOVERY_TIMEOUT,
    ):
        self._lock = threading.Lock()
        self._state = CircuitBreakerState.CLOSED
        self._failure_threshold = failure_threshold
        self._failure_window = failure_window
        self._recovery_timeout = recovery_timeout

        # Failure tracking
        self._failure_timestamps: list[float] = []
        self._consecutive_failures = 0

        # State transition timestamps
        self._opened_at: Optional[float] = None
        self._last_failure_at: Optional[float] = None
        self._last_success_at: Optional[float] = None

        # HALF_OPEN permit — only one probe request allowed at a time
        self._half_open_permit_taken = False

        # Counters for monitoring
        self._total_failures = 0
        self._total_successes = 0
        self._total_rejected = 0
        self._trip_count = 0

    @classmethod
    def get_instance(cls) -> 'CircuitBreaker':
        """Get or create the singleton circuit breaker."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
                    logger.info(
                        f"Circuit breaker initialized: threshold={cls._instance._failure_threshold}, "
                        f"window={cls._instance._failure_window}s, recovery={cls._instance._recovery_timeout}s"
                    )
        return cls._instance

    def check(self) -> None:
        """
        Check if requests are allowed through.

        Raises CircuitBreakerOpenError if the breaker is OPEN.
        Allows exactly one request through in HALF_OPEN state.
        """
        from exceptions import CircuitBreakerOpenError

        with self._lock:
            if self._state == CircuitBreakerState.CLOSED:
                return  # Normal — allow through

            if self._state == CircuitBreakerState.OPEN:
                # Check if recovery timeout has elapsed
                elapsed = time.monotonic() - self._opened_at
                if elapsed >= self._recovery_timeout:
                    self._state = CircuitBreakerState.HALF_OPEN
                    self._half_open_permit_taken = True
                    logger.info(
                        f"Circuit breaker OPEN -> HALF_OPEN after {elapsed:.1f}s — "
                        f"allowing probe request"
                    )
                    return  # Allow the ONE probe request

                # Still in recovery period — reject
                self._total_rejected += 1
                remaining = self._recovery_timeout - elapsed
                raise CircuitBreakerOpenError(
                    f"Circuit breaker OPEN — DB connections blocked for {remaining:.0f}s more "
                    f"(tripped after {self._failure_threshold} failures). "
                    f"Total rejected: {self._total_rejected}"
                )

            # HALF_OPEN — only allow if no probe is already in flight
            if self._half_open_permit_taken:
                self._total_rejected += 1
                raise CircuitBreakerOpenError(
                    f"Circuit breaker HALF_OPEN — probe request already in flight. "
                    f"Total rejected: {self._total_rejected}"
                )
            # Permit available (e.g., previous probe timed out without recording)
            self._half_open_permit_taken = True
            return

    def record_success(self) -> None:
        """Record a successful DB operation."""
        with self._lock:
            self._total_successes += 1
            self._last_success_at = time.monotonic()
            self._consecutive_failures = 0

            if self._state == CircuitBreakerState.HALF_OPEN:
                self._state = CircuitBreakerState.CLOSED
                self._failure_timestamps.clear()
                self._half_open_permit_taken = False
                logger.info("Circuit breaker HALF_OPEN -> CLOSED — DB recovered")

    def record_failure(self) -> None:
        """Record a failed DB operation."""
        with self._lock:
            now = time.monotonic()
            self._total_failures += 1
            self._consecutive_failures += 1
            self._last_failure_at = now

            if self._state == CircuitBreakerState.HALF_OPEN:
                # Probe failed — back to OPEN
                self._state = CircuitBreakerState.OPEN
                self._opened_at = now
                self._half_open_permit_taken = False
                logger.warning(
                    "Circuit breaker HALF_OPEN -> OPEN — probe failed, "
                    f"extending recovery timeout ({self._recovery_timeout}s)"
                )
                return

            if self._state == CircuitBreakerState.CLOSED:
                # Track failure in sliding window
                self._failure_timestamps.append(now)

                # Prune old failures outside the window
                cutoff = now - self._failure_window
                self._failure_timestamps = [
                    t for t in self._failure_timestamps if t > cutoff
                ]

                # Check if threshold exceeded within window
                if len(self._failure_timestamps) >= self._failure_threshold:
                    self._state = CircuitBreakerState.OPEN
                    self._opened_at = now
                    self._trip_count += 1
                    logger.error(
                        f"Circuit breaker CLOSED -> OPEN — "
                        f"{len(self._failure_timestamps)} failures in "
                        f"{self._failure_window}s (trip #{self._trip_count}). "
                        f"Blocking DB connections for {self._recovery_timeout}s."
                    )

    def get_stats(self) -> dict:
        """Get circuit breaker statistics for monitoring."""
        with self._lock:
            now = time.monotonic()
            stats = {
                'state': self._state.value,
                'failure_threshold': self._failure_threshold,
                'failure_window_seconds': self._failure_window,
                'recovery_timeout_seconds': self._recovery_timeout,
                'consecutive_failures': self._consecutive_failures,
                'recent_failures_in_window': len(self._failure_timestamps),
                'total_failures': self._total_failures,
                'total_successes': self._total_successes,
                'total_rejected': self._total_rejected,
                'trip_count': self._trip_count,
            }

            if self._state == CircuitBreakerState.OPEN and self._opened_at:
                elapsed = now - self._opened_at
                stats['open_for_seconds'] = round(elapsed, 1)
                stats['recovery_in_seconds'] = round(
                    max(0, self._recovery_timeout - elapsed), 1
                )

            return stats

    @classmethod
    def reset_for_testing(cls) -> None:
        """Reset singleton for testing. WARNING: Only use in tests."""
        with cls._instance_lock:
            cls._instance = None


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = [
    'CircuitBreaker',
    'CircuitBreakerState',
]
