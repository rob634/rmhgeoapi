# ============================================================================
# BLOB VALIDATION DECORATORS
# ============================================================================
# STATUS: Infrastructure - Fail-fast pre-flight validation for blob operations
# PURPOSE: DRY validation decorators for container/blob existence checks
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
Blob Validation Decorators - Fail-Fast Pre-Flight Checks.

Provides decorators for automatic container and blob validation before
repository method execution. Designed for ETL pipelines where blob reads
are numerous but one-time by nature.

Design Philosophy:
    - Fail fast with clear error messages
    - DRY - define validation logic once, apply everywhere
    - Declarative - method signatures clearly show what's validated
    - ETL-optimized - validate once before expensive operations

Exports:
    validate_container: Ensures container exists before operation
    validate_blob: Ensures blob exists before read/delete operations
    validate_container_and_blob: Combined validation (more efficient)
"""

# ============================================================================
# IMPORTS
# ============================================================================

from functools import wraps
from typing import Callable, Any
from azure.core.exceptions import ResourceNotFoundError
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, __name__)


# ============================================================================
# VALIDATION DECORATORS
# ============================================================================

def validate_container(func: Callable) -> Callable:
    """
    Decorator to validate container exists before method execution.

    Pre-flight check that fails fast if container doesn't exist.
    Use this for operations that require a valid container but don't
    need the blob to exist (e.g., write_blob, list_blobs).

    Expects method signature:
        func(self, container: str, ...)

    The decorator will:
    1. Call self.container_exists(container)
    2. Raise ResourceNotFoundError if container doesn't exist
    3. Execute original method if validation passes

    Args:
        func: Method to decorate (must have 'container' as first arg after self)

    Returns:
        Wrapped method with container validation

    Raises:
        ResourceNotFoundError: If container doesn't exist

    Example:
        @validate_container
        def write_blob(self, container: str, blob_path: str, data: bytes):
            # Container guaranteed to exist here
            # Blob doesn't need to exist (we're creating it)
            pass

        @validate_container
        def list_blobs(self, container: str, prefix: str = ""):
            # Container guaranteed to exist here
            pass
    """
    @wraps(func)
    def wrapper(self, container: str, *args, **kwargs) -> Any:
        # Pre-flight validation
        if not self.container_exists(container):
            error_msg = (
                f"Container '{container}' does not exist in storage account "
                f"'{self.account_name}'"
            )
            logger.error(f"❌ Container validation failed: {error_msg}")
            raise ResourceNotFoundError(error_msg)

        logger.debug(f"✅ Container validation passed: {container}")

        # Execute original method
        return func(self, container, *args, **kwargs)

    return wrapper


def validate_blob(func: Callable) -> Callable:
    """
    Decorator to validate blob exists before method execution.

    Pre-flight check that fails fast if blob doesn't exist.
    Use this in combination with @validate_container for read/delete operations.

    Expects method signature:
        func(self, container: str, blob_path: str, ...)

    The decorator will:
    1. Call self.blob_exists(container, blob_path)
    2. Raise ResourceNotFoundError if blob doesn't exist
    3. Execute original method if validation passes

    NOTE: This decorator assumes container exists. For combined validation,
    use @validate_container_and_blob instead (more efficient).

    Args:
        func: Method to decorate (must have 'container' and 'blob_path' as args)

    Returns:
        Wrapped method with blob validation

    Raises:
        ResourceNotFoundError: If blob doesn't exist

    Example:
        @validate_container  # Stack decorators
        @validate_blob
        def read_blob(self, container: str, blob_path: str) -> bytes:
            # Both container and blob guaranteed to exist
            pass
    """
    @wraps(func)
    def wrapper(self, container: str, blob_path: str, *args, **kwargs) -> Any:
        # Pre-flight validation
        if not self.blob_exists(container, blob_path):
            error_msg = f"Blob '{blob_path}' does not exist in container '{container}'"
            logger.error(f"❌ Blob validation failed: {error_msg}")
            raise ResourceNotFoundError(error_msg)

        logger.debug(f"✅ Blob validation passed: {container}/{blob_path}")

        # Execute original method
        return func(self, container, blob_path, *args, **kwargs)

    return wrapper


def validate_container_and_blob(func: Callable) -> Callable:
    """
    Decorator to validate both container and blob exist before method execution.

    Combined validation using validate_container_and_blob() method.
    More efficient than stacking @validate_container and @validate_blob
    because it uses a single validation call instead of two separate API calls.

    RECOMMENDED for read and delete operations in ETL pipelines where:
    - Both container and blob must exist
    - Operations are one-time (no caching benefit)
    - Clear errors are critical for debugging

    Expects method signature:
        func(self, container: str, blob_path: str, ...)

    The decorator will:
    1. Call self.validate_container_and_blob(container, blob_path)
    2. Raise ResourceNotFoundError if either doesn't exist with clear message
    3. Execute original method if validation passes

    Args:
        func: Method to decorate (must have 'container' and 'blob_path' as args)

    Returns:
        Wrapped method with combined validation

    Raises:
        ResourceNotFoundError: If container or blob doesn't exist

    Example:
        @validate_container_and_blob
        def read_blob(self, container: str, blob_path: str) -> bytes:
            # Both container and blob guaranteed to exist here
            # No validation boilerplate needed
            pass

        @validate_container_and_blob
        def delete_blob(self, container: str, blob_path: str) -> bool:
            # Both validated in single efficient check
            pass

    Performance Note:
        For ETL pipelines with one-time reads, this validation overhead is
        negligible compared to the time saved debugging cryptic errors.
    """
    @wraps(func)
    def wrapper(self, container: str, blob_path: str, *args, **kwargs) -> Any:
        # Single combined validation (efficient)
        validation = self.validate_container_and_blob(container, blob_path)

        if not validation['valid']:
            logger.error(f"❌ Validation failed: {validation['message']}")
            raise ResourceNotFoundError(validation['message'])

        logger.debug(
            f"✅ Container+Blob validation passed: {container}/{blob_path}"
        )

        # Execute original method
        return func(self, container, blob_path, *args, **kwargs)

    return wrapper


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'validate_container',
    'validate_blob',
    'validate_container_and_blob'
]