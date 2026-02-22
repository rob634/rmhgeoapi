# ============================================================================
# SYSTEM PARAMETERS SCHEMA
# ============================================================================
# STATUS: Core - System parameter validation schema
# PURPOSE: Define and validate execution context parameters (asset_id, etc.)
# CREATED: 08 FEB 2026
# EXPORTS: SYSTEM_PARAMETERS_SCHEMA, validate_system_params
# ============================================================================
"""
System Parameters Schema.

Defines validation rules for system-level parameters that are part of the
core data model, independent of specific job types.

System parameters represent the execution context:
- asset_id: The GeospatialAsset being processed (workflow output target)
- platform_id: The platform that originated the request (B2B source)
- request_id: The B2B request ID for callback routing

These are distinct from job parameters, which are business-logic specific
and defined in each job's parameters_schema.

Architecture:
    Parameters
    ├── SYSTEM PARAMETERS (Core Data Model - Execution Context)
    │   ├── asset_id        → FK to GeospatialAsset
    │   ├── platform_id     → FK to Platform
    │   └── request_id      → B2B request tracking
    │
    └── JOB PARAMETERS (Business Logic - Varies by Job Type)
        └── Defined in each job's parameters_schema

Usage:
    from core.schema.system_params import validate_system_params

    # In job validation:
    system_params = validate_system_params(raw_params)
    job_params = validate_job_schema(raw_params)
    validated = {**job_params, **system_params}

Exports:
    SYSTEM_PARAMETERS_SCHEMA: Schema definition for system params
    validate_system_params: Validation function
"""

from typing import Dict, Any, Optional


# ============================================================================
# SYSTEM PARAMETERS SCHEMA
# ============================================================================
# These parameters are part of the core data model and represent the
# execution context for any job, regardless of job type.
# ============================================================================

SYSTEM_PARAMETERS_SCHEMA = {
    # ========================================================================
    # ASSET LINKAGE (GeospatialAsset-centric data model)
    # ========================================================================
    'asset_id': {
        'type': 'str',
        'required': False,  # Not all jobs have assets (hello_world, maintenance)
        'max_length': 64,
        'description': 'FK to GeospatialAsset - the asset this job processes'
    },

    # ========================================================================
    # PLATFORM/B2B CONTEXT
    # ========================================================================
    'platform_id': {
        'type': 'str',
        'required': False,  # Internal jobs may not have platform
        'max_length': 50,
        'description': 'FK to Platform registry - B2B platform that submitted'
    },
    'request_id': {
        'type': 'str',
        'required': False,
        'max_length': 64,
        'description': 'B2B request ID for callback routing'
    },

    # ========================================================================
    # V0.9 RELEASE LINKAGE
    # ========================================================================
    'release_id': {
        'type': 'str',
        'required': False,
        'max_length': 64,
        'description': 'FK to AssetRelease - the versioned artifact this job produces'
    },

    # ========================================================================
    # LINEAGE (Version tracking - V0.8 Release Control)
    # ========================================================================
    'lineage_id': {
        'type': 'str',
        'required': False,
        'max_length': 64,
        'description': 'Version lineage identifier'
    },

    # ========================================================================
    # FUTURE: DAG Orchestration
    # ========================================================================
    # 'workflow_id': {
    #     'type': 'str',
    #     'required': False,
    #     'max_length': 64,
    #     'description': 'Workflow template identifier (for DAG orchestration)'
    # },
    # 'parent_job_id': {
    #     'type': 'str',
    #     'required': False,
    #     'max_length': 64,
    #     'description': 'Parent job ID (for sub-job/child workflows)'
    # },
}

# List of system parameter names for quick lookup
SYSTEM_PARAM_NAMES = set(SYSTEM_PARAMETERS_SCHEMA.keys())


def validate_system_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate and extract system parameters from raw params.

    Validates system-level parameters against SYSTEM_PARAMETERS_SCHEMA.
    Only returns params that are defined in the schema (ignores job params).

    Args:
        params: Raw parameters dict containing both system and job params

    Returns:
        Dict containing only validated system parameters

    Raises:
        ValueError: If a system parameter fails validation

    Example:
        >>> raw = {'asset_id': 'abc123', 'container_name': 'bronze'}
        >>> system = validate_system_params(raw)
        >>> system
        {'asset_id': 'abc123'}  # container_name filtered out
    """
    validated = {}

    for param_name, schema in SYSTEM_PARAMETERS_SCHEMA.items():
        value = params.get(param_name)

        # Skip if not present (all system params are optional)
        if value is None:
            continue

        # Type validation
        param_type = schema.get('type', 'str')

        if param_type == 'str':
            if not isinstance(value, str):
                raise ValueError(
                    f"System parameter '{param_name}' must be a string, "
                    f"got {type(value).__name__}"
                )

            # Length validation
            max_length = schema.get('max_length')
            if max_length and len(value) > max_length:
                raise ValueError(
                    f"System parameter '{param_name}' exceeds max length "
                    f"({len(value)} > {max_length})"
                )

        elif param_type == 'int':
            if not isinstance(value, int):
                raise ValueError(
                    f"System parameter '{param_name}' must be an integer, "
                    f"got {type(value).__name__}"
                )

        # Add validated param
        validated[param_name] = value

    return validated


def is_system_param(param_name: str) -> bool:
    """
    Check if a parameter name is a system parameter.

    Args:
        param_name: Name of the parameter to check

    Returns:
        True if param_name is a system parameter
    """
    return param_name in SYSTEM_PARAM_NAMES


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'SYSTEM_PARAMETERS_SCHEMA',
    'SYSTEM_PARAM_NAMES',
    'validate_system_params',
    'is_system_param',
]
