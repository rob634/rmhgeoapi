# ============================================================================
# CLAUDE CONTEXT - CONFIGURATION
# ============================================================================
# PURPOSE: Package initialization for Azure Geospatial ETL Pipeline architecture
# SOURCE: No direct configuration - provides package-level imports and documentation
# SCOPE: Package-level initialization and architectural documentation
# VALIDATION: No validation - package initialization with import verification
# ============================================================================

"""
Redesign Architecture - August 29, 2025

This module contains the complete architectural redesign based on:
- redesign.md specifications 
- JSON infrastructure design
- Job → Stage → Task abstraction pattern

Core Components:
- BaseController: Abstract controller with stage orchestration
- BaseStage: Sequential stage execution logic
- BaseTask: Parallel task execution within stages  
- BaseJob: Job state management and completion detection

Design Principles:
- Sequential stages with parallel tasks
- "Last task turns out the lights" completion pattern
- Atomic SQL operations for race condition prevention
- Queue-driven orchestration with Azure Functions
"""