# ============================================================================
# CLAUDE CONTEXT - RESOURCE VALIDATORS
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Infrastructure - Pre-flight resource validation
# PURPOSE: Centralized validators for blob/container/table existence checks
# LAST_REVIEWED: 28 NOV 2025
# EXPORTS: RESOURCE_VALIDATORS registry, run_validators, individual validators
# INTERFACES: ValidatorResult TypedDict
# PYDANTIC_MODELS: None (uses TypedDict for lightweight validation results)
# DEPENDENCIES: infrastructure.blob.BlobRepository, infrastructure.postgresql.PostgreSQLRepository
# SOURCE: Called by JobBaseMixin.validate_job_parameters() during job submission
# SCOPE: ALL job types that declare resource_validators
# VALIDATION: Blob existence, container existence, PostGIS table existence
# PATTERNS: Registry pattern, Strategy pattern (validators are interchangeable)
# ENTRY_POINTS: JobBaseMixin calls run_validators(cls.resource_validators, params)
# INDEX:
#   - ValidatorResult TypedDict: line 55
#   - RESOURCE_VALIDATORS registry: line 65
#   - run_validators: line 85
#   - validate_blob_exists: line 120
#   - validate_container_exists: line 175
#   - validate_table_exists: line 220
#   - validate_table_not_exists: line 275
#   - _get_zone_from_container: line 310 (helper)
# ============================================================================

"""
Pre-Flight Resource Validators

This module provides a registry of validation functions for checking external
resource existence BEFORE job creation. This prevents wasted database records
and queue messages for jobs that would fail immediately.

Usage in Job Classes:
    class ProcessVectorJob(JobBaseMixin, JobBase):
        resource_validators = [
            {
                'type': 'blob_exists',
                'container_param': 'container_name',
                'blob_param': 'blob_name',
                'error': 'Source file does not exist in Bronze storage'
            }
        ]

The JobBaseMixin.validate_job_parameters() method automatically runs these
validators after schema validation passes.

Validator Interface:
    def validator_fn(params: dict, config: dict) -> ValidatorResult:
        '''
        Args:
            params: Validated job parameters (after schema validation)
            config: Validator config from resource_validators declaration

        Returns:
            ValidatorResult with 'valid' bool and 'message' str
        '''

Author: Robert and Geospatial Claude Legion
Created: 28 NOV 2025
"""

from typing import Dict, Any, Callable, Optional, List
from typing_extensions import TypedDict
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, "validators")


class ValidatorResult(TypedDict):
    """Result from a resource validator."""
    valid: bool
    message: Optional[str]


# Type alias for validator functions
ValidatorFn = Callable[[Dict[str, Any], Dict[str, Any]], ValidatorResult]

# Registry of validator functions
RESOURCE_VALIDATORS: Dict[str, ValidatorFn] = {}


def register_validator(name: str):
    """Decorator to register a validator function."""
    def decorator(func: ValidatorFn) -> ValidatorFn:
        RESOURCE_VALIDATORS[name] = func
        logger.debug(f"Registered resource validator: {name}")
        return func
    return decorator


def run_validators(
    validators: List[Dict[str, Any]],
    params: Dict[str, Any]
) -> ValidatorResult:
    """
    Run a list of resource validators against job parameters.

    Args:
        validators: List of validator configurations from job class
        params: Validated job parameters

    Returns:
        ValidatorResult with 'valid' bool and 'message' str
        - valid=True if ALL validators pass
        - valid=False with message from FIRST failing validator

    Example:
        result = run_validators(cls.resource_validators, validated_params)
        if not result['valid']:
            raise ValueError(f"Pre-flight validation failed: {result['message']}")
    """
    for validator_config in validators:
        validator_type = validator_config.get('type')

        if not validator_type:
            return ValidatorResult(
                valid=False,
                message="Validator config missing 'type' field"
            )

        if validator_type not in RESOURCE_VALIDATORS:
            return ValidatorResult(
                valid=False,
                message=f"Unknown validator type: '{validator_type}'. Available: {list(RESOURCE_VALIDATORS.keys())}"
            )

        # Run the validator
        validator_fn = RESOURCE_VALIDATORS[validator_type]
        result = validator_fn(params, validator_config)

        if not result['valid']:
            # Return on first failure
            return result

    # All validators passed
    return ValidatorResult(valid=True, message=None)


# ============================================================================
# VALIDATOR IMPLEMENTATIONS
# ============================================================================

@register_validator("blob_exists")
def validate_blob_exists(params: Dict[str, Any], config: Dict[str, Any]) -> ValidatorResult:
    """
    Validate that a blob exists in Azure Blob Storage.

    Config options:
        container_param: str - Name of parameter containing container name
        blob_param: str - Name of parameter containing blob path
        zone: str - Optional trust zone ('bronze', 'silver', 'silverext').
                    If not specified, inferred from container name.
        error: str - Optional custom error message

    Example:
        resource_validators = [
            {
                'type': 'blob_exists',
                'container_param': 'container_name',
                'blob_param': 'blob_name',
                'zone': 'bronze',  # Optional
                'error': 'Source file not found'  # Optional
            }
        ]
    """
    from infrastructure.blob import BlobRepository

    # Extract parameter names from config
    container_param = config.get('container_param', 'container_name')
    blob_param = config.get('blob_param', 'blob_name')

    # Get actual values from job parameters
    container = params.get(container_param)
    blob_path = params.get(blob_param)

    if not container:
        return ValidatorResult(
            valid=False,
            message=f"Container parameter '{container_param}' is missing or empty"
        )

    if not blob_path:
        return ValidatorResult(
            valid=False,
            message=f"Blob parameter '{blob_param}' is missing or empty"
        )

    # Determine trust zone
    zone = config.get('zone') or _get_zone_from_container(container)

    try:
        blob_repo = BlobRepository.for_zone(zone)
        validation = blob_repo.validate_container_and_blob(container, blob_path)

        if validation['valid']:
            logger.debug(f"✅ Pre-flight: blob exists: {container}/{blob_path}")
            return ValidatorResult(valid=True, message=None)
        else:
            error_msg = config.get('error') or validation['message']
            logger.warning(f"❌ Pre-flight: {error_msg}")
            return ValidatorResult(valid=False, message=error_msg)

    except Exception as e:
        error_msg = f"Failed to validate blob existence: {e}"
        logger.error(error_msg)
        return ValidatorResult(valid=False, message=error_msg)


@register_validator("container_exists")
def validate_container_exists(params: Dict[str, Any], config: Dict[str, Any]) -> ValidatorResult:
    """
    Validate that a container exists in Azure Blob Storage.

    Config options:
        container_param: str - Name of parameter containing container name
        zone: str - Optional trust zone ('bronze', 'silver', 'silverext')
        error: str - Optional custom error message

    Example:
        resource_validators = [
            {
                'type': 'container_exists',
                'container_param': 'source_container',
                'error': 'Source container does not exist'
            }
        ]
    """
    from infrastructure.blob import BlobRepository

    container_param = config.get('container_param', 'container_name')
    container = params.get(container_param)

    if not container:
        return ValidatorResult(
            valid=False,
            message=f"Container parameter '{container_param}' is missing or empty"
        )

    zone = config.get('zone') or _get_zone_from_container(container)

    try:
        blob_repo = BlobRepository.for_zone(zone)

        if blob_repo.container_exists(container):
            logger.debug(f"✅ Pre-flight: container exists: {container}")
            return ValidatorResult(valid=True, message=None)
        else:
            error_msg = config.get('error') or f"Container '{container}' does not exist"
            logger.warning(f"❌ Pre-flight: {error_msg}")
            return ValidatorResult(valid=False, message=error_msg)

    except Exception as e:
        error_msg = f"Failed to validate container existence: {e}"
        logger.error(error_msg)
        return ValidatorResult(valid=False, message=error_msg)


@register_validator("table_exists")
def validate_table_exists(params: Dict[str, Any], config: Dict[str, Any]) -> ValidatorResult:
    """
    Validate that a PostGIS table exists.

    Config options:
        table_param: str - Name of parameter containing table name
        schema_param: str - Name of parameter containing schema name (default: 'schema')
        default_schema: str - Default schema if not in params (default: 'geo')
        error: str - Optional custom error message

    Example:
        resource_validators = [
            {
                'type': 'table_exists',
                'table_param': 'source_table',
                'schema_param': 'source_schema',
                'error': 'Source table does not exist'
            }
        ]

    NOTE: Uses dict_row cursor factory - access columns by name, not index!
    """
    from infrastructure.postgresql import PostgreSQLRepository

    table_param = config.get('table_param', 'table_name')
    schema_param = config.get('schema_param', 'schema')
    default_schema = config.get('default_schema', 'geo')

    table_name = params.get(table_param)
    schema = params.get(schema_param, default_schema)

    if not table_name:
        return ValidatorResult(
            valid=False,
            message=f"Table parameter '{table_param}' is missing or empty"
        )

    try:
        repo = PostgreSQLRepository()
        with repo._get_connection() as conn:
            with conn.cursor() as cur:
                # NOTE: Use 'as exists' alias and access via ['exists'] - dict_row pattern!
                cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = %s AND table_name = %s
                    ) as exists
                """, (schema, table_name))
                exists = cur.fetchone()['exists']

        if exists:
            logger.debug(f"✅ Pre-flight: table exists: {schema}.{table_name}")
            return ValidatorResult(valid=True, message=None)
        else:
            error_msg = config.get('error') or f"Table '{schema}.{table_name}' does not exist"
            logger.warning(f"❌ Pre-flight: {error_msg}")
            return ValidatorResult(valid=False, message=error_msg)

    except Exception as e:
        error_msg = f"Failed to validate table existence: {e}"
        logger.error(error_msg)
        return ValidatorResult(valid=False, message=error_msg)


@register_validator("table_not_exists")
def validate_table_not_exists(params: Dict[str, Any], config: Dict[str, Any]) -> ValidatorResult:
    """
    Validate that a PostGIS table does NOT exist (for create-new-table jobs).

    Config options:
        table_param: str - Name of parameter containing table name
        schema_param: str - Name of parameter containing schema name (default: 'schema')
        default_schema: str - Default schema if not in params (default: 'geo')
        allow_overwrite_param: str - If this param is True, skip validation
        error: str - Optional custom error message

    Example:
        resource_validators = [
            {
                'type': 'table_not_exists',
                'table_param': 'table_name',
                'allow_overwrite_param': 'overwrite',
                'error': 'Table already exists. Set overwrite=true to replace.'
            }
        ]
    """
    # Check if overwrite is allowed
    allow_overwrite_param = config.get('allow_overwrite_param')
    if allow_overwrite_param and params.get(allow_overwrite_param):
        logger.debug(f"✅ Pre-flight: table_not_exists skipped (overwrite={params.get(allow_overwrite_param)})")
        return ValidatorResult(valid=True, message=None)

    # Inverse of table_exists
    result = validate_table_exists(params, config)

    if result['valid']:
        # Table exists - this is a FAILURE for table_not_exists
        table_param = config.get('table_param', 'table_name')
        schema_param = config.get('schema_param', 'schema')
        default_schema = config.get('default_schema', 'geo')
        table_name = params.get(table_param)
        schema = params.get(schema_param, default_schema)

        error_msg = config.get('error') or f"Table '{schema}.{table_name}' already exists"
        return ValidatorResult(valid=False, message=error_msg)
    else:
        # Table doesn't exist - this is SUCCESS for table_not_exists
        # (unless the check itself failed due to connection error)
        if result.get('message') and "Failed to validate" in result['message']:
            return result  # Propagate connection errors
        return ValidatorResult(valid=True, message=None)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _get_zone_from_container(container_name: str) -> str:
    """
    Infer trust zone from container name.

    Container naming convention:
        - bronze-* or *bronze* → 'bronze'
        - silver-* or *silver* → 'silver'
        - silverext-* or *external* → 'silverext'
        - Default → 'silver'

    Args:
        container_name: Azure Blob Storage container name

    Returns:
        Trust zone: 'bronze', 'silver', or 'silverext'
    """
    container_lower = container_name.lower()

    if 'bronze' in container_lower:
        return 'bronze'
    elif 'external' in container_lower or 'silverext' in container_lower:
        return 'silverext'
    elif 'silver' in container_lower:
        return 'silver'
    else:
        # Default to bronze (most common for source data in ETL)
        return 'bronze'


# ============================================================================
# MODULE EXPORTS
# ============================================================================

__all__ = [
    'ValidatorResult',
    'ValidatorFn',
    'RESOURCE_VALIDATORS',
    'register_validator',
    'run_validators',
    'validate_blob_exists',
    'validate_container_exists',
    'validate_table_exists',
    'validate_table_not_exists',
]
