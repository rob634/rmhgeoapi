# ============================================================================
# CLAUDE CONTEXT - EXCEPTIONS
# ============================================================================
# EPOCH: SHARED - BOTH EPOCHS
# STATUS: Used by Epoch 3 and Epoch 4
# NOTE: Careful migration required
# PURPOSE: Custom exception hierarchy for distinguishing contract violations from business failures
# EXPORTS: ContractViolationError, BusinessLogicError, ServiceBusError, DatabaseError, TaskExecutionError
# INTERFACES: Standard Python exception hierarchy
# PYDANTIC_MODELS: None
# DEPENDENCIES: None (standard library only)
# SOURCE: Clean architecture error handling strategy
# SCOPE: Application-wide exception handling
# VALIDATION: Type checking and contract enforcement
# PATTERNS: Exception hierarchy for error categorization
# ENTRY_POINTS: Raised at component boundaries for contract violations
# INDEX: ContractViolationError:30, BusinessLogicError:50, Specific errors:70
# ============================================================================

"""
Custom Exception Hierarchy

Distinguishes between:
1. Contract Violations (programming bugs that need fixing)
2. Business Logic Failures (expected runtime issues)

This separation ensures bugs are found quickly while the system
remains robust to expected failures.

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