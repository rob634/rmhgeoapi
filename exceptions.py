# ============================================================================
# CUSTOM EXCEPTION HIERARCHY
# ============================================================================
# STATUS: Core - Error handling foundation
# PURPOSE: Distinguish contract violations (bugs) from business logic failures
# LAST_REVIEWED: 02 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure)
# ============================================================================
"""
Custom Exception Hierarchy.

Distinguishes between:
    1. Contract Violations (programming bugs) - should NEVER be caught
    2. Business Logic Failures (expected runtime issues) - handle gracefully

Error Handling Strategy:
    - ContractViolationError: Let bubble up, fix the code
    - BusinessLogicError subclasses: Catch and handle appropriately

Exports:
    ContractViolationError: Programming bugs that need fixing
    BusinessLogicError: Base class for business failures
    ServiceBusError: Service Bus communication failures
    DatabaseError: Database operation failures
    TaskExecutionError: Task execution failures
    ResourceNotFoundError: Missing resource errors
    ValidationError: Business validation failures
    ConfigurationError: Fatal system misconfiguration
"""


class ContractViolationError(TypeError):
    """
    Raised when component contracts are violated (programming bugs).

    These indicate:
    - Wrong types passed to functions
    - Missing required fields
    - Enum type mismatches
    - Interface contract violations

    These should NEVER be caught and handled - they indicate bugs
    that need to be fixed in the code.

    Examples:
        - Controller returns dict instead of TaskResult
        - Repository receives string instead of JobStatus enum
        - Task processor returns wrong type
    """
    pass


class BusinessLogicError(Exception):
    """
    Base class for expected runtime business logic failures.

    These are normal failures that occur during system operation
    and should be handled gracefully without crashing.

    Subclasses represent specific categories of business failures.
    """
    pass


class ServiceBusError(BusinessLogicError):
    """
    Service Bus communication failures.

    Examples:
        - Service Bus unavailable
        - Queue not found
        - Message size exceeded
        - Authentication failure
        - Network timeout
    """
    pass


class DatabaseError(BusinessLogicError):
    """
    Database operation failures.

    Examples:
        - Connection lost
        - Deadlock detected
        - Constraint violation
        - Query timeout
        - Transaction rollback
    """
    pass


class TaskExecutionError(BusinessLogicError):
    """
    Task failed during execution.

    Examples:
        - File not found in blob storage
        - Raster file corrupted
        - Invalid data format
        - External API unavailable
        - Insufficient permissions
    """
    pass


class ResourceNotFoundError(BusinessLogicError):
    """
    Requested resource does not exist.

    Examples:
        - Blob not found in container
        - Job ID not in database
        - Task handler not registered
        - Queue does not exist
    """
    pass


class ValidationError(BusinessLogicError):
    """
    Business validation failed.

    Note: This is different from ContractViolationError.
    This is for business rule validation, not type contracts.

    Examples:
        - Raster resolution too low
        - File size exceeds limit
        - Invalid coordinate system
        - Unsupported file format
    """
    pass


class ConfigurationError(Exception):
    """
    System configuration error.

    These are typically fatal and indicate misconfiguration
    that prevents the system from operating.

    Examples:
        - Missing required environment variables
        - Invalid connection strings
        - Malformed configuration files
    """
    pass