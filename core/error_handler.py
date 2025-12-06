"""
CoreMachine Error Handler - Centralized Error Handling.

Provides context manager for consistent error logging and handling across
CoreMachine operations. Eliminates duplicate try-catch patterns.

Exports:
    CoreMachineErrorHandler: Context manager for operation error handling
    log_nested_error: Helper for preserving exception context in cleanup
"""

from contextlib import contextmanager
from typing import Optional, Callable, Any, Dict
import traceback
import logging

from exceptions import ContractViolationError


class CoreMachineErrorHandler:
    """
    Centralized error handling for CoreMachine operations.

    Provides context manager for consistent error logging, structured
    error context, and optional error callbacks.

    Usage:
        with CoreMachineErrorHandler.handle_operation(
            logger=self.logger,
            operation_name="fetch job record",
            job_id=job_id,
            on_error=lambda e: self._mark_job_failed(job_id, str(e)),
            raise_on_error=True
        ):
            job_record = self.repos['job_repo'].get_job(job_id)
    """

    @staticmethod
    @contextmanager
    def handle_operation(
        logger: logging.Logger,
        operation_name: str,
        job_id: Optional[str] = None,
        task_id: Optional[str] = None,
        stage: Optional[int] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        raise_on_error: bool = True
    ):
        """
        Context manager for consistent error handling.

        Args:
            logger: Logger instance for error output
            operation_name: Human-readable operation description
            job_id: Optional job ID for context
            task_id: Optional task ID for context
            stage: Optional stage number for context
            on_error: Optional callback to execute on error (e.g., mark job failed)
            raise_on_error: If True, re-raise exception after handling

        Yields:
            None (context manager)

        Raises:
            ContractViolationError: Always re-raised (programming bugs)
            Exception: Re-raised if raise_on_error=True

        Usage Pattern 1 (with re-raise):
            with CoreMachineErrorHandler.handle_operation(
                self.logger, "fetch job", job_id=job_id
            ):
                job = self.repos['job_repo'].get_job(job_id)

        Usage Pattern 2 (without re-raise, return None):
            with CoreMachineErrorHandler.handle_operation(
                self.logger, "fetch job", job_id=job_id, raise_on_error=False
            ):
                job = self.repos['job_repo'].get_job(job_id)
            if job is None:
                # Handle gracefully
        """
        try:
            yield
        except ContractViolationError:
            # Contract violations always bubble up (programming bugs)
            raise
        except Exception as e:
            # Build structured error context
            error_context: Dict[str, Any] = {
                'operation': operation_name,
                'error_type': type(e).__name__,
                'error_message': str(e),
            }
            if job_id:
                error_context['job_id'] = job_id[:16] + '...' if len(job_id) > 16 else job_id
            if task_id:
                error_context['task_id'] = task_id[:16] + '...' if len(task_id) > 16 else task_id
            if stage:
                error_context['stage'] = stage

            # Structured error logging (Application Insights friendly)
            logger.error(
                f"❌ Operation failed: {operation_name}",
                extra=error_context
            )
            logger.debug(f"Traceback: {traceback.format_exc()}")

            # Execute error callback if provided
            if on_error:
                try:
                    on_error(e)
                    logger.debug(f"✅ Error callback executed successfully")
                except Exception as callback_error:
                    logger.error(
                        f"❌ Error callback failed: {callback_error}",
                        extra={'callback_error': str(callback_error)}
                    )

            # Re-raise or return None
            if raise_on_error:
                raise


def log_nested_error(
    logger: logging.Logger,
    primary_error: Exception,
    cleanup_error: Exception,
    operation: str,
    job_id: Optional[str] = None,
    task_id: Optional[str] = None,
    stage: Optional[int] = None,
    additional_context: Optional[Dict[str, Any]] = None
) -> None:
    """
    Log both primary and cleanup errors with full context preservation.

    When a cleanup operation (like marking a job as failed) fails after a
    primary error, this function ensures BOTH errors are logged with full
    context. This is critical for debugging because otherwise the original
    root cause error gets lost.

    Args:
        logger: Logger instance
        primary_error: The original error that triggered cleanup
        cleanup_error: The error that occurred during cleanup
        operation: Description of what operation was being performed
        job_id: Optional job ID for context
        task_id: Optional task ID for context
        stage: Optional stage number for context
        additional_context: Optional dict of extra context fields

    Usage:
        except Exception as stage_error:
            try:
                self.state_manager.mark_job_failed(job_id, str(stage_error))
            except Exception as cleanup_error:
                log_nested_error(
                    self.logger,
                    primary_error=stage_error,
                    cleanup_error=cleanup_error,
                    operation="stage_advancement",
                    job_id=job_id,
                    stage=stage
                )

    In Application Insights, you can search for:
        - customDimensions.primary_error_type to find root cause
        - customDimensions.cleanup_error_type to find cleanup failures
        - customDimensions.nested_error = true to find all nested errors
    """
    # Build comprehensive error context
    error_context: Dict[str, Any] = {
        'nested_error': True,  # Flag for easy filtering in Application Insights
        'operation': operation,
        # Primary error (the root cause)
        'primary_error': str(primary_error),
        'primary_error_type': type(primary_error).__name__,
        # Cleanup error (the symptom)
        'cleanup_error': str(cleanup_error),
        'cleanup_error_type': type(cleanup_error).__name__,
    }

    # Add optional context
    if job_id:
        error_context['job_id'] = job_id[:16] + '...' if len(job_id) > 16 else job_id
    if task_id:
        error_context['task_id'] = task_id[:16] + '...' if len(task_id) > 16 else task_id
    if stage is not None:
        error_context['stage'] = stage
    if additional_context:
        error_context.update(additional_context)

    # Log with full context
    logger.error(
        f"❌ Nested error: {operation} failed, cleanup also failed. "
        f"PRIMARY: {type(primary_error).__name__}: {primary_error} | "
        f"CLEANUP: {type(cleanup_error).__name__}: {cleanup_error}",
        extra=error_context
    )

    # Also log traceback at debug level for detailed investigation
    logger.debug(f"Primary error traceback: {traceback.format_exception(type(primary_error), primary_error, primary_error.__traceback__)}")
