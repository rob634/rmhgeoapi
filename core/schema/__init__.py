# ============================================================================
# CLAUDE CONTEXT - CORE SCHEMA PACKAGE
# ============================================================================
# CATEGORY: SCHEMAS - DATA VALIDATION & TRANSFORMATION
# PURPOSE: Pydantic models for validation, serialization, and data flow
# EPOCH: Shared by all epochs (not persisted to database)# PURPOSE: Database schema management for core framework
# EXPORTS: SQL generation and schema deployment classes
# AZURE FUNCTIONS: Required for package imports
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