# ============================================================================
# CLAUDE CONTEXT - METRICS INTERFACE MODULE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Web Interface - Pipeline Observability Metrics
# PURPOSE: HTTP endpoints and dashboard for real-time job progress monitoring
# LAST_REVIEWED: 28 DEC 2025
# EXPORTS: MetricsInterface
# DEPENDENCIES: web_interfaces.base, infrastructure.metrics_repository
# ============================================================================
"""
Metrics Interface Module.

Provides HTTP endpoints and dashboard for pipeline observability:
- GET /api/interface/metrics - Dashboard with real-time progress
- HTMX fragments for live updates

See interface.py for implementation.
"""

from .interface import MetricsInterface

__all__ = ['MetricsInterface']
