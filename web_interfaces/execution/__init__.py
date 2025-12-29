# ============================================================================
# CLAUDE CONTEXT - JOB EXECUTION DASHBOARD MODULE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Web Interface - Unified Job Execution Dashboard
# PURPOSE: Combined job monitoring with metrics, progress, and task details
# LAST_REVIEWED: 29 DEC 2025
# EXPORTS: ExecutionInterface
# DEPENDENCIES: web_interfaces.base, infrastructure.metrics_repository
# ============================================================================
"""
Job Execution Dashboard module.

Unified interface for monitoring job execution with two modes:
- Overview: All active jobs + historical jobs table
- Detail: Single job with tasks, stages, and detailed metrics

Exports the ExecutionInterface class for registration.
"""

from web_interfaces.execution.interface import ExecutionInterface

__all__ = ['ExecutionInterface']
