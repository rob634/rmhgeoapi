"""
Core Database Schema Management Package.

Contains SQL DDL generation, schema deployment, and PostgreSQL functions.

Exports:
    PydanticToSQL: SQL DDL generator from Pydantic models
    SchemaManager, SchemaManagerFactory: Schema deployment utilities
    WorkflowDefinition, WorkflowStageDefinition: Workflow schema models
    JobQueueMessage, TaskQueueMessage: Queue message schemas
    TaskUpdateModel, JobUpdateModel: Database update models
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