# Defensive DB Connection Hardening — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent PostgreSQL OOM/failure cascades by adding health checks, circuit breaking, pool recovery, and transient retry.

**Architecture:** 4 independent layers of defense, each in its own task. No new dependencies.

**Tech Stack:** psycopg3, psycopg_pool, Python threading/time

---

## Task 1: P0 — Pool Health Check (connection_pool.py)

**Files:**
- Modify: `infrastructure/connection_pool.py:278-286` (pool creation)

- [ ] **Step 1: Add `check` parameter to ConnectionPool**

In `_create_pool()` at line 278, add `check=ConnectionPool.check_connection` to the pool constructor:

```python
pool = ConnectionPool(
    conninfo=conn_string,
    min_size=config['min_size'],
    max_size=config['max_size'],
    timeout=config['timeout'],
    max_lifetime=config['max_lifetime'],
    configure=cls._configure_connection,
    check=ConnectionPool.check_connection,  # Ping before checkout — discard dead connections
    open=True,
)
```

This makes psycopg_pool run a lightweight protocol-level ping on each connection before handing it to a caller. Dead/SSL-broken connections are automatically discarded and replaced.

- [ ] **Step 2: Verify no import changes needed**

`ConnectionPool.check_connection` is a built-in static method on `psycopg_pool.ConnectionPool`. No additional imports required.

- [ ] **Step 3: Commit**

```bash
git add infrastructure/connection_pool.py
git commit -m "feat: add connection health check to pool — P0 defensive DB hardening"
```

---

## Task 2: P1 — Circuit Breaker (new module)

**Files:**
- Create: `infrastructure/circuit_breaker.py`
- Modify: `infrastructure/postgresql.py` — integrate into `_get_connection()`
- Modify: `infrastructure/__init__.py` — add lazy import + `__all__` entry
- Modify: `exceptions.py` — add `CircuitBreakerOpenError`

### Step 1: Add CircuitBreakerOpenError to exceptions.py

- [ ] Add after `DatabaseError` (line ~90):

```python
class CircuitBreakerOpenError(DatabaseError):
    """
    Circuit breaker is open — database connections are temporarily blocked.

    Raised when the circuit breaker has tripped due to consecutive
    connection failures. Callers should back off and retry later.
    """
    pass
```

### Step 2: Create infrastructure/circuit_breaker.py

- [ ] Create the circuit breaker module:

```python
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
    CLOSED  → Normal operation. All requests go through.
    OPEN    → DB is down. Fail fast for `recovery_timeout` seconds.
    HALF_OPEN → Probe: allow ONE request through to test recovery.

Transitions:
    CLOSED → OPEN: `failure_threshold` failures within `failure_window` seconds.
    OPEN → HALF_OPEN: `recovery_timeout` seconds elapsed.
    HALF_OPEN → CLOSED: Probe request succeeds.
    HALF_OPEN → OPEN: Probe request fails (reset recovery timer).
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
                    logger.info(
                        f"Circuit breaker OPEN → HALF_OPEN after {elapsed:.1f}s — "
                        f"allowing probe request"
                    )
                    return  # Allow probe request

                # Still in recovery period — reject
                self._total_rejected += 1
                remaining = self._recovery_timeout - elapsed
                raise CircuitBreakerOpenError(
                    f"Circuit breaker OPEN — DB connections blocked for {remaining:.0f}s more "
                    f"(tripped after {self._failure_threshold} failures). "
                    f"Total rejected: {self._total_rejected}"
                )

            # HALF_OPEN — allow through (probe request)
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
                logger.info("Circuit breaker HALF_OPEN → CLOSED — DB recovered")

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
                logger.warning(
                    "Circuit breaker HALF_OPEN → OPEN — probe failed, "
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
                        f"Circuit breaker CLOSED → OPEN — "
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
```

### Step 3: Register in infrastructure/__init__.py

- [ ] Add TYPE_CHECKING import (after line 100):

```python
from .circuit_breaker import CircuitBreaker as _CircuitBreaker
```

- [ ] Add lazy import case in `__getattr__` (before the `else` clause at line 292):

```python
elif name == "CircuitBreaker":
    from .circuit_breaker import CircuitBreaker
    return CircuitBreaker
```

- [ ] Add to `__all__` list:

```python
"CircuitBreaker",
```

### Step 4: Integrate into postgresql.py `_get_connection()`

- [ ] Add circuit breaker check at the top of `_get_connection()` (after line 749, before the pool mode check):

```python
# Circuit breaker — fail fast if DB is known to be down
from infrastructure.circuit_breaker import CircuitBreaker
breaker = CircuitBreaker.get_instance()
breaker.check()  # Raises CircuitBreakerOpenError if OPEN
```

- [ ] Wrap both `_get_pooled_connection` and `_get_single_use_connection` yields to record success/failure. In `_get_connection()`, replace the simple delegation with:

```python
from infrastructure.circuit_breaker import CircuitBreaker
breaker = CircuitBreaker.get_instance()
breaker.check()  # Raises CircuitBreakerOpenError if OPEN

from infrastructure.connection_pool import ConnectionPoolManager

try:
    if ConnectionPoolManager.is_pool_mode():
        with self._get_pooled_connection() as conn:
            breaker.record_success()
            yield conn
    else:
        with self._get_single_use_connection() as conn:
            breaker.record_success()
            yield conn
except Exception:
    breaker.record_failure()
    raise
```

### Step 5: Add circuit breaker stats to pool stats reporting

- [ ] In `docker_health/classic_worker.py`, extend `_check_connection_pool()` to include circuit breaker stats:

After line 194 (`pool_stats = ConnectionPoolManager.get_pool_stats()`), add:

```python
from infrastructure.circuit_breaker import CircuitBreaker
cb_stats = CircuitBreaker.get_instance().get_stats()
pool_stats['circuit_breaker'] = cb_stats
pool_has_error = "error" in pool_stats or cb_stats.get('state') != 'closed'
```

### Step 6: Commit

```bash
git add exceptions.py infrastructure/circuit_breaker.py infrastructure/__init__.py infrastructure/postgresql.py docker_health/classic_worker.py
git commit -m "feat: add circuit breaker for DB connections — P1 defensive DB hardening"
```

---

## Task 3: P2 — Automatic Pool Recovery (postgresql.py)

**Files:**
- Modify: `infrastructure/postgresql.py:762-799` (`_get_pooled_connection`)

### Step 1: Add dead-pool detection and auto-recovery

- [ ] Replace the except block in `_get_pooled_connection()` (lines 786-799) to add pool recovery on non-auth errors:

The current code only retries on auth errors. Add detection for dead-pool indicators (SSL errors, "connection lost", broken pipe) and trigger `recreate_pool()`:

```python
except Exception as e:
    error_str = str(e).lower()
    logger.error(f"❌ Pool connection error: {e}")

    # Dead-pool indicators — SSL broken, connection lost, etc.
    dead_pool_markers = [
        "ssl syscall error",
        "connection is closed",
        "the connection is lost",
        "broken pipe",
        "connection reset",
        "server closed the connection unexpectedly",
    ]
    is_dead_pool = any(marker in error_str for marker in dead_pool_markers)

    can_retry = (
        attempt < max_attempts
        and (
            (use_managed_identity and self._is_managed_identity_auth_error(e))
            or is_dead_pool
        )
    )

    if not can_retry:
        raise

    if is_dead_pool:
        logger.warning(
            f"🔄 Dead pool detected ({type(e).__name__}); "
            f"recreating connection pool and retrying"
        )
        ConnectionPoolManager.recreate_pool()
    else:
        logger.warning(
            "🔄 Pooled managed identity auth failed; "
            "refreshing token, recreating pool, retrying once"
        )
        self._refresh_pooled_managed_identity_credentials()
```

### Step 2: Increase max_attempts to 2 for all cases

- [ ] Change line 774 from:

```python
max_attempts = 2 if use_managed_identity else 1
```

to:

```python
max_attempts = 2  # Always allow 1 retry — auth refresh OR dead-pool recovery
```

### Step 3: Add ConnectionPoolManager import at top of method

- [ ] The `ConnectionPoolManager` import already exists at line 770. Verify it's accessible in the except block (it is — it's at method scope before the loop).

### Step 4: Commit

```bash
git add infrastructure/postgresql.py
git commit -m "feat: auto-recover from dead connection pool — P2 defensive DB hardening"
```

---

## Task 4: P3 — Transient Retry in Single-Use Path (postgresql.py)

**Files:**
- Modify: `infrastructure/postgresql.py:801-879` (`_get_single_use_connection`)

### Step 1: Add transient error detection

- [ ] Add a static method to `PostgreSQLRepository` (after `_is_managed_identity_auth_error`, around line 657):

```python
@staticmethod
def _is_transient_connection_error(error: Exception) -> bool:
    """
    Return True when error looks like a transient connection issue
    that may succeed on retry (network blip, server restart, etc.).
    """
    transient_markers = [
        "connection is closed",
        "the connection is lost",
        "could not connect to server",
        "connection refused",
        "connection timed out",
        "ssl syscall error",
        "broken pipe",
        "connection reset",
        "server closed the connection unexpectedly",
    ]
    for candidate in (error, getattr(error, '__cause__', None), getattr(error, '__context__', None)):
        if candidate is None:
            continue
        msg = str(candidate).lower()
        if any(marker in msg for marker in transient_markers):
            return True
    return False
```

### Step 2: Extend retry logic in _get_single_use_connection

- [ ] Change max_attempts on line 811 from:

```python
max_attempts = 2 if use_managed_identity else 1
```

to:

```python
max_attempts = 2  # Always allow 1 retry — auth refresh OR transient recovery
```

- [ ] In the except block (lines 858-868), extend the `can_retry` logic:

```python
can_retry = (
    attempt < max_attempts
    and (
        (use_managed_identity and self._is_managed_identity_auth_error(e))
        or self._is_transient_connection_error(e)
    )
)

if not can_retry:
    raise

if use_managed_identity and self._is_managed_identity_auth_error(e):
    logger.warning("🔄 Managed identity auth failed; refreshing token and retrying connection")
    self._refresh_managed_identity_conn_string()
else:
    logger.warning(f"🔄 Transient connection error ({type(e).__name__}); retrying in 2s")
    import time
    time.sleep(2)
```

### Step 3: Commit

```bash
git add infrastructure/postgresql.py
git commit -m "feat: add transient retry for single-use connections — P3 defensive DB hardening"
```

---

## Completion

After all 4 tasks are implemented and committed, verify with:

```bash
# Ensure all files parse
python -c "from infrastructure.circuit_breaker import CircuitBreaker; print('OK')"
python -c "from infrastructure.connection_pool import ConnectionPoolManager; print('OK')"
python -c "from infrastructure.postgresql import PostgreSQLRepository; print('OK')"
python -c "from exceptions import CircuitBreakerOpenError; print('OK')"
```
