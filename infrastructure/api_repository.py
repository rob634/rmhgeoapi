# ============================================================================
# CLAUDE CONTEXT - API REPOSITORY BASE
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Infrastructure - External API access base class
# PURPOSE: Abstract base for authenticated external API access with retry,
#          session management, and request logging
# LAST_REVIEWED: 20 MAR 2026
# EXPORTS: APIRepository
# DEPENDENCIES: requests, logging, abc
# ============================================================================

import logging
import time
from abc import ABC, abstractmethod

import requests

logger = logging.getLogger(__name__)

# Transient HTTP status codes that warrant a retry with backoff
_TRANSIENT_STATUS_CODES = {429, 502, 503}


class APIRepository(ABC):
    """
    Base class for external API access.

    Owns auth lifecycle, session management, retry, and request logging.
    Subclasses implement their specific auth flow.

    Pattern: same as BlobRepository.for_zone() and PostgreSQLRepository —
    handlers never manage credentials directly.

    Subclasses must implement:
        authenticate()    — acquire initial credentials
        refresh_token()   — refresh expired credentials
        get_auth_headers() — return headers dict for authenticated requests
    """

    def __init__(self, base_url: str, timeout: int = 60, max_retries: int = 3) -> None:
        """
        Args:
            base_url:    Root URL for the external API (no trailing slash required).
            timeout:     Per-request timeout in seconds.
            max_retries: Maximum retry attempts for transient errors (429/502/503).
        """
        self._base_url: str = base_url.rstrip("/")
        self._timeout: int = timeout
        self._max_retries: int = max_retries
        self._authenticated: bool = False
        self._session: requests.Session = requests.Session()

    # ------------------------------------------------------------------
    # Abstract interface — subclasses must implement
    # ------------------------------------------------------------------

    @abstractmethod
    def authenticate(self) -> None:
        """Acquire initial credentials and store them on the instance."""

    @abstractmethod
    def refresh_token(self) -> None:
        """Refresh expired credentials and update stored state."""

    @abstractmethod
    def get_auth_headers(self) -> dict:
        """
        Return headers required for authenticated requests.

        Example:
            {"Authorization": "Bearer <token>"}
        """

    # ------------------------------------------------------------------
    # Credential-key construction
    # ------------------------------------------------------------------

    @classmethod
    def from_credential_key(cls, credential_key: str, **kwargs) -> "APIRepository":
        """
        Construct an authenticated APIRepository from a logical credential key.

        Resolves credentials via KeyVaultRepository (Key Vault + env var fallback),
        then delegates to the subclass _from_credentials() hook.

        Args:
            credential_key: Logical name (e.g. "acled", "ibat").

        Returns:
            Fully constructed subclass instance.

        Raises:
            VaultAccessError: If credentials cannot be resolved.
            ContractViolationError: If auth_type is incompatible with subclass.
        """
        from infrastructure.vault import KeyVaultRepository

        vault = KeyVaultRepository.instance()
        creds = vault.resolve_credentials(credential_key)
        return cls._from_credentials(creds, **kwargs)

    @classmethod
    def _from_credentials(cls, creds: dict, **kwargs) -> "APIRepository":
        """
        Subclass hook: build instance from a resolved credential dict.

        Override in subclasses. Default raises NotImplementedError.
        """
        raise NotImplementedError(
            f"{cls.__name__} must implement _from_credentials() "
            f"to support from_credential_key() construction."
        )

    # ------------------------------------------------------------------
    # Public request interface
    # ------------------------------------------------------------------

    def get(self, url: str, params=None, **kwargs) -> requests.Response:
        """Convenience wrapper for GET requests."""
        return self.request("GET", url, params=params, **kwargs)

    def post(self, url: str, data=None, json=None, **kwargs) -> requests.Response:
        """Convenience wrapper for POST requests."""
        return self.request("POST", url, data=data, json=json, **kwargs)

    def request(
        self,
        method: str,
        url: str,
        params=None,
        data=None,
        json=None,
        **kwargs,
    ) -> requests.Response:
        """
        Execute an authenticated HTTP request with retry and logging.

        Behaviour:
        - Ensures authentication before the first request.
        - Injects auth headers on every attempt.
        - On 401: refreshes token and retries exactly once.
        - On transient errors (429, 502, 503): retries up to max_retries
          with exponential backoff (2**attempt seconds). Respects the
          Retry-After header when present on 429 responses.
        - On all other non-2xx responses: raises immediately.

        Args:
            method: HTTP method string (e.g. "GET", "POST").
            url:    Full URL or path relative to base_url.
            params: Query string parameters.
            data:   Form-encoded request body.
            json:   JSON-serialisable request body.
            **kwargs: Passed through to requests.Session.request().

        Returns:
            requests.Response with a successful (non-error) status.

        Raises:
            requests.HTTPError: For non-transient HTTP errors.
            requests.RequestException: For connection-level failures.
        """
        self._ensure_authenticated()

        # Normalise the URL — allow callers to pass a bare path
        if not url.startswith("http"):
            url = f"{self._base_url}/{url.lstrip('/')}"

        token_refreshed = False

        for attempt in range(self._max_retries + 1):
            headers = {**kwargs.pop("headers", {}), **self.get_auth_headers()}
            start = time.monotonic()

            try:
                response = self._session.request(
                    method=method,
                    url=url,
                    params=params,
                    data=data,
                    json=json,
                    headers=headers,
                    timeout=self._timeout,
                    **kwargs,
                )
            except requests.RequestException:
                logger.exception(
                    "Request failed [%s %s] attempt=%d/%d",
                    method,
                    url,
                    attempt + 1,
                    self._max_retries + 1,
                )
                raise

            duration_ms = (time.monotonic() - start) * 1000
            logger.info(
                "%s %s -> %d (%.0f ms)",
                method,
                url,
                response.status_code,
                duration_ms,
            )

            # Success
            if response.ok:
                return response

            # 401 — attempt a single token refresh
            if response.status_code == 401 and not token_refreshed:
                logger.warning(
                    "401 Unauthorized for %s %s — refreshing token and retrying",
                    method,
                    url,
                )
                self.refresh_token()
                token_refreshed = True
                # Do NOT consume an attempt slot for the auth retry
                continue

            # Transient errors — backoff and retry
            if response.status_code in _TRANSIENT_STATUS_CODES:
                if attempt >= self._max_retries:
                    logger.error(
                        "Transient error %d for %s %s — max retries (%d) exhausted",
                        response.status_code,
                        method,
                        url,
                        self._max_retries,
                    )
                    response.raise_for_status()

                backoff = self._backoff_seconds(response, attempt)
                logger.warning(
                    "Transient error %d for %s %s — backing off %.1fs (attempt %d/%d)",
                    response.status_code,
                    method,
                    url,
                    backoff,
                    attempt + 1,
                    self._max_retries,
                )
                time.sleep(backoff)
                continue

            # Non-transient error — raise immediately
            logger.error(
                "Non-transient error %d for %s %s",
                response.status_code,
                method,
                url,
            )
            response.raise_for_status()

        # Should be unreachable, but satisfies the type checker
        raise RuntimeError(  # pragma: no cover
            f"request() exhausted retry loop without returning for {method} {url}"
        )

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying requests.Session and release connections."""
        self._session.close()
        logger.debug("APIRepository session closed for %s", self._base_url)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_authenticated(self) -> None:
        """Call authenticate() exactly once before the first request."""
        if not self._authenticated:
            logger.debug("Not yet authenticated — calling authenticate()")
            self.authenticate()
            self._authenticated = True

    @staticmethod
    def _backoff_seconds(response: requests.Response, attempt: int) -> float:
        """
        Return the number of seconds to wait before the next retry.

        Uses the Retry-After header when present (429 responses), otherwise
        falls back to exponential backoff: 2**attempt (1s, 2s, 4s, …).
        """
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                return float(retry_after)
            except ValueError:
                pass  # Non-numeric value — fall through to exponential backoff
        return float(2 ** attempt)
