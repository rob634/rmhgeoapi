# ============================================================================
# TOKEN CACHE - Thread-safe OAuth token caching
# ============================================================================
# STATUS: Infrastructure - Token caching for Docker runtime
# PURPOSE: Cache OAuth tokens with expiry tracking and automatic refresh
# LAST_REVIEWED: 10 JAN 2026
# ============================================================================
"""
Thread-safe token caching with expiry tracking.

Provides reusable cache classes for OAuth tokens used by Docker workers.
Tokens are cached with their expiration time and automatically invalidated
when approaching expiry.

Azure AD Token Lifecycle:
------------------------
- Tokens typically expire after 1 hour (3600 seconds)
- We refresh 5 minutes before expiry (TOKEN_REFRESH_BUFFER_SECS)
- Background thread refreshes every 45 minutes (BACKGROUND_REFRESH_INTERVAL_SECS)

Usage:
------
```python
cache = TokenCache()

# Check for valid cached token (with 5 min buffer)
token = cache.get_if_valid(min_ttl_seconds=300)
if token:
    return token

# Acquire new token and cache it
new_token, expires_at = acquire_token()
cache.set(new_token, expires_at)
```
"""

from datetime import datetime, timezone
from threading import Lock
from typing import Optional
from dataclasses import dataclass, field


@dataclass
class TokenCache:
    """
    Thread-safe cache for OAuth tokens with expiry tracking.

    Features:
    - Thread-safe access via Lock
    - TTL-aware retrieval (won't return nearly-expired tokens)
    - Status reporting for health checks
    - Explicit invalidation for forced refresh
    """

    token: Optional[str] = None
    expires_at: Optional[datetime] = None
    _lock: Lock = field(default_factory=Lock, repr=False)

    def get_if_valid(self, min_ttl_seconds: int = 300) -> Optional[str]:
        """
        Return cached token if valid and not expiring soon.

        Args:
            min_ttl_seconds: Minimum time-to-live required. Returns None
                            if token expires sooner than this threshold.
                            Default: 300 (5 minutes)

        Returns:
            Cached token if valid, None otherwise.
        """
        with self._lock:
            if not self.token or not self.expires_at:
                return None

            ttl = (self.expires_at - datetime.now(timezone.utc)).total_seconds()
            if ttl > min_ttl_seconds:
                return self.token
            return None

    def set(self, token: str, expires_at: datetime) -> None:
        """
        Update cached token.

        Args:
            token: The OAuth token string.
            expires_at: Token expiration time (must be timezone-aware).
        """
        with self._lock:
            self.token = token
            self.expires_at = expires_at

    def invalidate(self) -> None:
        """Force token refresh on next access by clearing expiry."""
        with self._lock:
            self.expires_at = None

    def clear(self) -> None:
        """Completely clear the cache."""
        with self._lock:
            self.token = None
            self.expires_at = None

    def ttl_seconds(self) -> Optional[float]:
        """
        Return seconds until expiry, or None if no token.

        Returns:
            Seconds until token expires, or None if no valid token.
        """
        with self._lock:
            if not self.expires_at:
                return None
            return (self.expires_at - datetime.now(timezone.utc)).total_seconds()

    @property
    def is_valid(self) -> bool:
        """Check if token exists and hasn't expired."""
        with self._lock:
            if not self.token or not self.expires_at:
                return False
            return self.expires_at > datetime.now(timezone.utc)

    def get_status(self) -> dict:
        """
        Get cache status for health checks.

        Returns:
            Dict with token presence, TTL, and expiry time.
        """
        with self._lock:
            if not self.token or not self.expires_at:
                return {"has_token": False, "ttl_seconds": None, "expires_at": None}

            ttl = (self.expires_at - datetime.now(timezone.utc)).total_seconds()
            return {
                "has_token": True,
                "ttl_seconds": max(0, int(ttl)),
                "expires_at": self.expires_at.isoformat(),
            }


@dataclass
class ErrorCache:
    """
    Track last error for health reporting.

    Maintains error history for diagnosing connection issues
    in health check endpoints.
    """

    last_error: Optional[str] = None
    last_error_time: Optional[datetime] = None
    last_success_time: Optional[datetime] = None
    _lock: Lock = field(default_factory=Lock, repr=False)

    def record_success(self) -> None:
        """Record a successful operation, clearing last error."""
        with self._lock:
            self.last_error = None
            self.last_success_time = datetime.now(timezone.utc)

    def record_error(self, error: str) -> None:
        """
        Record an error.

        Args:
            error: Error message to store.
        """
        with self._lock:
            self.last_error = error
            self.last_error_time = datetime.now(timezone.utc)

    def get_status(self) -> dict:
        """
        Get error status for health checks.

        Returns:
            Dict with last error, error time, and success time.
        """
        with self._lock:
            return {
                "last_error": self.last_error,
                "last_error_time": (
                    self.last_error_time.isoformat() if self.last_error_time else None
                ),
                "last_success_time": (
                    self.last_success_time.isoformat() if self.last_success_time else None
                ),
            }

    @property
    def has_error(self) -> bool:
        """Check if there's a recorded error."""
        with self._lock:
            return self.last_error is not None


# =============================================================================
# Global cache instances
# =============================================================================

postgres_token_cache = TokenCache()
"""Cache for PostgreSQL OAuth tokens (managed identity mode)."""

storage_token_cache = TokenCache()
"""Cache for Azure Storage OAuth tokens."""

db_error_cache = ErrorCache()
"""Cache for database connection errors."""

storage_error_cache = ErrorCache()
"""Cache for storage connection errors."""
