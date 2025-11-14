# ============================================================================
# CLAUDE CONTEXT - ERROR HANDLING
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Core utility - Centralized error handling for CoreMachine
# PURPOSE: Eliminate duplicate error logging patterns with context manager
# LAST_REVIEWED: 13 NOV 2025
# EXPORTS: CoreMachineErrorHandler (context manager)
# INTERFACES: None (utility class)
# PYDANTIC_MODELS: None
# DEPENDENCIES: logging, traceback, contextlib, typing
# SOURCE: Extracted from core/machine.py duplicate patterns
# SCOPE: CoreMachine error handling
# VALIDATION: None
# PATTERNS: Context Manager, Structured Logging
# ENTRY_POINTS: with CoreMachineErrorHandler.handle_operation(...)
# INDEX: CoreMachineErrorHandler:40, handle_operation:80
# ============================================================================

"""
CoreMachine Error Handler - Centralized Error Handling

Provides context manager for consistent error logging and handling across
CoreMachine operations. Eliminates 18 duplicate try-catch patterns.

Author: Robert and Geospatial Claude Legion
Date: 13 NOV 2025
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
