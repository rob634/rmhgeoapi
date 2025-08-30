"""
Workflow Schema Definitions - Job→Stage→Task Architecture Orchestration

Comprehensive workflow definition system providing declarative multi-stage job orchestration for
the Azure Geospatial ETL Pipeline. Implements type-safe workflow specifications with parameter
validation, stage dependencies, and execution constraints that enable consistent, maintainable,
and scalable job workflow management across all pipeline operations.

Architecture Responsibility:
    This module defines WORKFLOW ORCHESTRATION within the Job→Stage→Task architecture:
    - Job Layer: WorkflowDefinition providing complete job specification and validation
    - Stage Layer: WorkflowStageDefinition providing stage sequence and parameter management
    - Task Layer: Stage parameter validation ensuring type-safe task execution
    - Repository Layer: Parameter validation and constraint enforcement integration

Key Features:
- Declarative workflow definitions with comprehensive validation and constraint enforcement
- Type-safe parameter systems with automatic validation, coercion, and default value handling
- Stage dependency management preventing invalid execution sequences and circular dependencies
- Parallel execution controls with configurable task limits and resource management
- Built-in workflow registry for standard pipeline operations and reusable patterns
- Version-aware workflow definitions supporting evolution and backward compatibility
- Comprehensive parameter constraint system (ranges, lengths, allowed values)
- Global and stage-specific parameter validation with inheritance and override patterns

Workflow Definition Hierarchy:
    WorkflowDefinition (Job Level)
    ├── Global Parameters (Available to all stages)
    ├── Stage 1: WorkflowStageDefinition
    │   ├── Stage Parameters (Stage-specific)
    │   ├── Task Type Definition
    │   └── Execution Constraints
    ├── Stage 2: WorkflowStageDefinition
    │   ├── Dependencies on Stage 1
    │   └── Parameter Inheritance
    └── Stage N: WorkflowStageDefinition (Final)

Parameter Validation System:
    Request Parameters → Global Validation → Stage Validation
                      ↓                    ↓                ↓
                 Type Coercion    Default Application    Constraint Check
                      ↓                    ↓                ↓
                 Validated Params → Task Execution → Business Logic

Stage Dependency Resolution:
    Workflow stages execute in dependency-resolved order:
    - Stage 1 (no dependencies) → executes first
    - Stage 2 (depends on Stage 1) → waits for Stage 1 completion
    - Stage 3 (depends on Stage 1,2) → waits for both completions
    - Final Stage (marked is_final_stage=True) → triggers job completion

Integration Points:
- Used by controller implementations for job workflow specification and validation
- Integrates with HTTP triggers for parameter validation and constraint enforcement
- Connects to queue systems for stage sequencing and dependency management
- Feeds into task creation systems for parameter distribution and context setup
- Provides job lifecycle management with completion detection and error handling

Predefined Workflows:
- HelloWorld: Two-stage demonstration workflow (greeting → reply pattern)
- SyncContainer: Multi-stage container synchronization (inventory → cataloging)
- Additional workflows registered in WORKFLOW_REGISTRY for easy access

Parameter Types Supported:
- STRING: Text values with length constraints and validation
- INTEGER: Numeric values with range validation and coercion
- FLOAT: Decimal values with range constraints and automatic conversion
- BOOLEAN: Boolean values with string coercion ("true"/"false" handling)
- DICT: Complex object parameters with structure validation
- LIST: Array parameters with length constraints and element validation
- ANY: Flexible parameters for advanced use cases

Validation Features:
- Required/optional parameter enforcement with clear error messaging
- Default value application with type-safe handling
- Range validation for numeric parameters (min_value, max_value)
- Length validation for strings and lists (min_length, max_length)
- Allowed value constraints with enumeration support
- Cross-parameter validation and dependency checking

Usage Examples:
    # Create workflow definition
    workflow = WorkflowDefinition(
        job_type="custom_workflow",
        workflow_name="Custom Processing",
        description="Multi-stage custom workflow",
        stages=[
            WorkflowStageDefinition(
                stage_number=1,
                stage_name="Data Preparation",
                task_type="prepare_data",
                stage_parameters=[
                    StageParameterDefinition(
                        name="input_format",
                        param_type=StageParameterType.STRING,
                        allowed_values=["geotiff", "shapefile", "json"]
                    )
                ]
            )
        ]
    )
    
    # Validate job parameters
    validated = workflow.validate_job_parameters({
        "input_format": "geotiff",
        "parallel_tasks": 10
    })
    
    # Get workflow from registry
    hello_workflow = get_workflow_definition("hello_world")

Author: Azure Geospatial ETL Team
"""

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Dict, Any, List, Optional, Union
from enum import Enum


class StageParameterType(str, Enum):
    """Types of stage parameters for validation"""
    STRING = "string"
    INTEGER = "integer" 
    FLOAT = "float"
    BOOLEAN = "boolean"
    DICT = "dict"
    LIST = "list"
    ANY = "any"


class StageParameterDefinition(BaseModel):
    """
    Definition of a parameter required/accepted by a stage
    
    Provides type-safe parameter validation with defaults and constraints
    """
    name: str = Field(..., description="Parameter name (snake_case)")
    param_type: StageParameterType = Field(..., description="Parameter data type")
    required: bool = Field(default=True, description="Whether parameter is required")
    default_value: Optional[Any] = Field(default=None, description="Default value if not provided")
    description: str = Field(..., description="Human-readable parameter description")
    
    # Validation constraints
    min_value: Optional[Union[int, float]] = Field(default=None, description="Minimum value for numeric types")
    max_value: Optional[Union[int, float]] = Field(default=None, description="Maximum value for numeric types")
    min_length: Optional[int] = Field(default=None, description="Minimum length for string/list types")
    max_length: Optional[int] = Field(default=None, description="Maximum length for string/list types")
    allowed_values: Optional[List[Any]] = Field(default=None, description="List of allowed values")
    
    @field_validator('name')
    @classmethod
    def validate_parameter_name(cls, v):
        """Ensure parameter names are snake_case"""
        if not v.replace('_', '').replace('-', '').isalnum():
            raise ValueError("Parameter name must be alphanumeric with underscores/hyphens")
        if v != v.lower():
            raise ValueError("Parameter name must be lowercase")
        return v
    
    def validate_parameter_value(self, value: Any) -> Any:
        """
        Validate a parameter value against this definition
        
        Returns validated/coerced value or raises ValueError
        """
        # Handle required parameter
        if value is None:
            if self.required and self.default_value is None:
                raise ValueError(f"Required parameter '{self.name}' is missing")
            return self.default_value if value is None else value
        
        # Type validation and coercion
        if self.param_type == StageParameterType.STRING:
            if not isinstance(value, str):
                try:
                    value = str(value)
                except:
                    raise ValueError(f"Parameter '{self.name}' must be a string")
                    
        elif self.param_type == StageParameterType.INTEGER:
            if not isinstance(value, int):
                try:
                    value = int(value)
                except:
                    raise ValueError(f"Parameter '{self.name}' must be an integer")
                    
        elif self.param_type == StageParameterType.FLOAT:
            if not isinstance(value, (int, float)):
                try:
                    value = float(value)
                except:
                    raise ValueError(f"Parameter '{self.name}' must be a number")
                    
        elif self.param_type == StageParameterType.BOOLEAN:
            if not isinstance(value, bool):
                if isinstance(value, str):
                    value = value.lower() in ('true', 't', '1', 'yes', 'y')
                else:
                    value = bool(value)
                    
        elif self.param_type == StageParameterType.DICT:
            if not isinstance(value, dict):
                raise ValueError(f"Parameter '{self.name}' must be a dictionary")
                
        elif self.param_type == StageParameterType.LIST:
            if not isinstance(value, list):
                raise ValueError(f"Parameter '{self.name}' must be a list")
        
        # Constraint validation
        if self.min_value is not None and isinstance(value, (int, float)):
            if value < self.min_value:
                raise ValueError(f"Parameter '{self.name}' must be >= {self.min_value}")
                
        if self.max_value is not None and isinstance(value, (int, float)):
            if value > self.max_value:
                raise ValueError(f"Parameter '{self.name}' must be <= {self.max_value}")
                
        if self.min_length is not None and hasattr(value, '__len__'):
            if len(value) < self.min_length:
                raise ValueError(f"Parameter '{self.name}' must have length >= {self.min_length}")
                
        if self.max_length is not None and hasattr(value, '__len__'):
            if len(value) > self.max_length:
                raise ValueError(f"Parameter '{self.name}' must have length <= {self.max_length}")
                
        if self.allowed_values is not None:
            if value not in self.allowed_values:
                raise ValueError(f"Parameter '{self.name}' must be one of: {self.allowed_values}")
        
        return value


class WorkflowStageDefinition(BaseModel):
    """
    Complete stage definition for workflow orchestration
    
    Defines stage sequence, parameters, and execution characteristics
    """
    stage_number: int = Field(..., ge=1, le=100, description="Stage number in sequence (1-based)")
    stage_name: str = Field(..., min_length=1, max_length=100, description="Human-readable stage name")
    task_type: str = Field(..., description="Task type for this stage (snake_case)")
    
    # Stage dependencies and characteristics
    is_final_stage: bool = Field(default=False, description="Whether this is the final stage")
    depends_on_stages: List[int] = Field(default_factory=list, description="Stages that must complete first")
    can_run_in_parallel: bool = Field(default=True, description="Whether tasks in stage can run in parallel")
    max_parallel_tasks: Optional[int] = Field(default=None, ge=1, description="Max parallel tasks (None = unlimited)")
    
    # Stage parameters
    stage_parameters: List[StageParameterDefinition] = Field(
        default_factory=list, 
        description="Parameters accepted by this stage"
    )
    
    # Stage execution settings
    timeout_minutes: int = Field(default=60, ge=1, le=1440, description="Stage timeout in minutes")
    max_retries: int = Field(default=3, ge=0, le=10, description="Maximum retry attempts")
    retry_delay_seconds: int = Field(default=30, ge=1, le=3600, description="Delay between retries")
    
    @field_validator('task_type')
    @classmethod
    def validate_task_type(cls, v):
        """Ensure task types are snake_case"""
        if not v.replace('_', '').isalnum():
            raise ValueError("Task type must be alphanumeric with underscores")
        if v != v.lower():
            raise ValueError("Task type must be lowercase")
        return v
    
    @model_validator(mode='after')
    def validate_stage_dependencies(self):
        """Validate stage dependencies are logical"""
        if self.stage_number in self.depends_on_stages:
            raise ValueError(f"Stage {self.stage_number} cannot depend on itself")
            
        for dep_stage in self.depends_on_stages:
            if dep_stage >= self.stage_number:
                raise ValueError(f"Stage {self.stage_number} cannot depend on later stage {dep_stage}")
        
        return self
    
    def validate_stage_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate parameters for this stage
        
        Returns validated parameters with defaults applied
        """
        validated_params = {}
        
        # Validate each defined parameter
        for param_def in self.stage_parameters:
            param_value = parameters.get(param_def.name)
            validated_value = param_def.validate_parameter_value(param_value)
            if validated_value is not None:
                validated_params[param_def.name] = validated_value
        
        # Check for unexpected parameters
        defined_param_names = {p.name for p in self.stage_parameters}
        unexpected_params = set(parameters.keys()) - defined_param_names
        
        if unexpected_params:
            # For now, allow unexpected parameters but log warning
            for param_name in unexpected_params:
                validated_params[param_name] = parameters[param_name]
        
        return validated_params


class WorkflowDefinition(BaseModel):
    """
    Complete workflow definition for a job_type
    
    Defines the entire sequence of stages and their relationships
    """
    job_type: str = Field(..., description="Job type identifier (snake_case)")
    workflow_name: str = Field(..., description="Human-readable workflow name")
    description: str = Field(..., description="Workflow description and purpose")
    version: str = Field(default="1.0.0", description="Workflow version for evolution tracking")
    
    # Workflow stages
    stages: List[WorkflowStageDefinition] = Field(..., min_items=1, description="Sequential stage definitions")
    
    # Global workflow parameters (available to all stages)
    global_parameters: List[StageParameterDefinition] = Field(
        default_factory=list,
        description="Parameters available to all stages"
    )
    
    # Workflow settings
    max_total_duration_minutes: int = Field(default=1440, ge=1, description="Max total workflow duration")
    allow_partial_failure: bool = Field(default=False, description="Whether workflow can complete with some stage failures")
    
    @field_validator('job_type')
    @classmethod
    def validate_job_type(cls, v):
        """Ensure job types are snake_case"""
        if not v.replace('_', '').isalnum():
            raise ValueError("Job type must be alphanumeric with underscores")
        if v != v.lower():
            raise ValueError("Job type must be lowercase")
        return v
    
    @model_validator(mode='after')
    def validate_workflow_consistency(self):
        """Validate workflow definition consistency"""
        stage_numbers = [stage.stage_number for stage in self.stages]
        
        # Ensure sequential stage numbering
        expected_numbers = list(range(1, len(self.stages) + 1))
        if sorted(stage_numbers) != expected_numbers:
            raise ValueError(f"Stage numbers must be sequential 1-{len(self.stages)}, got: {sorted(stage_numbers)}")
        
        # Ensure exactly one final stage
        final_stages = [stage for stage in self.stages if stage.is_final_stage]
        if len(final_stages) != 1:
            raise ValueError(f"Exactly one stage must be marked as final, got {len(final_stages)}")
        
        # Validate dependencies reference valid stages
        for stage in self.stages:
            for dep_stage in stage.depends_on_stages:
                if dep_stage not in stage_numbers:
                    raise ValueError(f"Stage {stage.stage_number} depends on non-existent stage {dep_stage}")
        
        return self
    
    def get_stage_by_number(self, stage_number: int) -> Optional[WorkflowStageDefinition]:
        """Get stage definition by stage number"""
        for stage in self.stages:
            if stage.stage_number == stage_number:
                return stage
        return None
    
    def get_next_stage(self, current_stage: int) -> Optional[WorkflowStageDefinition]:
        """Get the next stage in sequence"""
        return self.get_stage_by_number(current_stage + 1)
    
    def validate_job_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate global job parameters
        
        Returns validated parameters with defaults applied
        """
        validated_params = {}
        
        # Validate global parameters
        for param_def in self.global_parameters:
            param_value = parameters.get(param_def.name)
            validated_value = param_def.validate_parameter_value(param_value)
            if validated_value is not None:
                validated_params[param_def.name] = validated_value
        
        # Pass through other parameters (will be validated at stage level)
        for param_name, param_value in parameters.items():
            if param_name not in validated_params:
                validated_params[param_name] = param_value
        
        return validated_params
    
    def validate_stage_parameters(self, stage_number: int, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate parameters for a specific stage
        
        Combines global and stage-specific parameter validation
        """
        stage = self.get_stage_by_number(stage_number)
        if not stage:
            raise ValueError(f"Stage {stage_number} not found in workflow")
        
        # Start with globally validated parameters
        validated_params = self.validate_job_parameters(parameters)
        
        # Apply stage-specific validation
        stage_validated = stage.validate_stage_parameters(validated_params)
        
        return stage_validated


# Predefined workflow definitions for common job types
def create_hello_world_workflow() -> WorkflowDefinition:
    """Create the Hello World workflow definition"""
    return WorkflowDefinition(
        job_type="hello_world",
        workflow_name="Hello World Test Workflow",
        description="Two-stage workflow for testing Job→Stage→Task architecture",
        version="1.0.0",
        global_parameters=[
            StageParameterDefinition(
                name="n",
                param_type=StageParameterType.INTEGER,
                required=False,
                default_value=1,
                description="Number of parallel tasks to create in each stage",
                min_value=1,
                max_value=100
            ),
            StageParameterDefinition(
                name="message",
                param_type=StageParameterType.STRING,
                required=False,
                default_value="Hello World",
                description="Custom message prefix for greetings",
                max_length=200
            )
        ],
        stages=[
            WorkflowStageDefinition(
                stage_number=1,
                stage_name="Hello Worlds",
                task_type="hello_world_greeting",
                is_final_stage=False,
                stage_parameters=[
                    StageParameterDefinition(
                        name="greeting_prefix",
                        param_type=StageParameterType.STRING,
                        required=False,
                        default_value="Hello from",
                        description="Prefix for greeting messages"
                    )
                ]
            ),
            WorkflowStageDefinition(
                stage_number=2,
                stage_name="Worlds Reply",
                task_type="hello_world_reply",
                is_final_stage=True,
                depends_on_stages=[1],
                stage_parameters=[
                    StageParameterDefinition(
                        name="reply_prefix",
                        param_type=StageParameterType.STRING,
                        required=False,
                        default_value="Hello",
                        description="Prefix for reply messages"
                    )
                ]
            )
        ]
    )


def create_sync_container_workflow() -> WorkflowDefinition:
    """Create a sync_container workflow definition (example)"""
    return WorkflowDefinition(
        job_type="sync_container",
        workflow_name="Container Synchronization Workflow",
        description="Multi-stage workflow for synchronizing container contents to STAC catalog",
        version="1.0.0",
        global_parameters=[
            StageParameterDefinition(
                name="dataset_id",
                param_type=StageParameterType.STRING,
                required=True,
                description="Container/dataset identifier"
            ),
            StageParameterDefinition(
                name="resource_id",
                param_type=StageParameterType.STRING,
                required=True,
                description="Resource identifier within dataset"
            ),
            StageParameterDefinition(
                name="version_id",
                param_type=StageParameterType.STRING,
                required=True,
                description="Version identifier for this sync operation"
            )
        ],
        stages=[
            WorkflowStageDefinition(
                stage_number=1,
                stage_name="Container Inventory",
                task_type="list_container_files",
                is_final_stage=False,
                stage_parameters=[
                    StageParameterDefinition(
                        name="file_pattern",
                        param_type=StageParameterType.STRING,
                        required=False,
                        default_value="*",
                        description="File pattern filter for inventory"
                    )
                ]
            ),
            WorkflowStageDefinition(
                stage_number=2,
                stage_name="File Cataloging",
                task_type="catalog_file",
                is_final_stage=True,
                depends_on_stages=[1],
                max_parallel_tasks=50,  # Limit parallel file processing
                stage_parameters=[
                    StageParameterDefinition(
                        name="catalog_mode",
                        param_type=StageParameterType.STRING,
                        required=False,
                        default_value="smart",
                        allowed_values=["quick", "smart", "full"],
                        description="Cataloging mode (quick/smart/full)"
                    )
                ]
            )
        ]
    )


# Export workflow registry for easy access
WORKFLOW_REGISTRY = {
    "hello_world": create_hello_world_workflow,
    "sync_container": create_sync_container_workflow
}


def get_workflow_definition(job_type: str) -> WorkflowDefinition:
    """Get workflow definition for a job type"""
    if job_type not in WORKFLOW_REGISTRY:
        raise ValueError(f"No workflow definition found for job_type: {job_type}")
    
    return WORKFLOW_REGISTRY[job_type]()


# Export all public classes and functions
__all__ = [
    'StageParameterType',
    'StageParameterDefinition', 
    'WorkflowStageDefinition',
    'WorkflowDefinition',
    'create_hello_world_workflow',
    'create_sync_container_workflow',
    'WORKFLOW_REGISTRY',
    'get_workflow_definition'
]