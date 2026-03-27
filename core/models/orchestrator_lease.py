# ============================================================================
# CLAUDE CONTEXT - ORCHESTRATOR LEASE MODEL
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Core - Distributed mutex for DAG Brain instances
# PURPOSE: Single-row lease model for orchestrator exclusion via DB TTL
# LAST_REVIEWED: 26 MAR 2026
# EXPORTS: OrchestratorLease
# DEPENDENCIES: pydantic, datetime
# ============================================================================
"""
Orchestrator lease model — distributed mutex for DAG Brain instances.

A single row acts as a lease. The holder renews it every poll cycle.
If the holder crashes, the lease expires and another instance takes over.
"""
from datetime import datetime
from typing import Any, ClassVar, Dict, List, Optional

from pydantic import BaseModel


class OrchestratorLease(BaseModel):
    """Single-row lease for orchestrator exclusion."""

    lease_key: str = "singleton"
    holder_id: str
    acquired_at: datetime
    expires_at: datetime
    renewed_at: datetime

    # DDL generation hints (same pattern as WorkflowRun in core/models/workflow_run.py)
    __sql_table_name: ClassVar[str] = "orchestrator_lease"
    __sql_schema: ClassVar[str] = "app"
    __sql_primary_key: ClassVar[List[str]] = ["lease_key"]
    __sql_foreign_keys: ClassVar[Dict[str, str]] = {}
    __sql_unique_constraints: ClassVar[List[Dict[str, Any]]] = []
    __sql_indexes: ClassVar[List[Dict[str, Any]]] = []
