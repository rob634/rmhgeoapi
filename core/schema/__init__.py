# ============================================================================
# CLAUDE CONTEXT - CORE SCHEMA PACKAGE
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Core schema - Database schema management and validation
# PURPOSE: Database schema management and message validation for core framework
# LAST_REVIEWED: 16 OCT 2025
# EXPORTS: SQL generation, schema deployment, queue messages, update models
# INTERFACES: Package initialization only
# PYDANTIC_MODELS: Exported from submodules (queue, updates, workflow)
# DEPENDENCIES: Core schema submodules
# AZURE_FUNCTIONS: Required for package imports
# PATTERNS: Package initialization, Schema management
# ENTRY_POINTS: from core.schema import JobQueueMessage, TaskUpdateModel
# ============================================================================

"""
Core database schema management package.

This package contains:
- SQL DDL generation from Pydantic models
- Schema deployment and management
- PostgreSQL function definitions
"""

# Export schema management utilities
from .sql_generator import PydanticToSQL
from .deployer import SchemaManager, SchemaManagerFactory

# Export workflow schemas
from .workflow import (
    WorkflowDefinition,
    WorkflowStageDefinition,
    StageParameterDefinition,
    StageParameterType,
    get_workflow_definition
)

# Export orchestration schemas
from .orchestration import (
    OrchestrationAction,
    OrchestrationInstruction,
    OrchestrationItem,
    FileOrchestrationItem
)

# Export queue schemas
from .queue import (
    JobQueueMessage,
    TaskQueueMessage
)

# Export update models
from .updates import (
    TaskUpdateModel,
    JobUpdateModel,
    StageCompletionUpdateModel
)

__all__ = [
    # Schema management
    'PydanticToSQL',
    'SchemaManager',
    'SchemaManagerFactory',

    # Workflow schemas
    'WorkflowDefinition',
    'WorkflowStageDefinition',
    'StageParameterDefinition',
    'StageParameterType',
    'get_workflow_definition',

    # Orchestration schemas
    'OrchestrationAction',
    'OrchestrationInstruction',
    'OrchestrationItem',
    'FileOrchestrationItem',

    # Queue schemas
    'JobQueueMessage',
    'TaskQueueMessage',

    # Update models
    'TaskUpdateModel',
    'JobUpdateModel',
    'StageCompletionUpdateModel'
]