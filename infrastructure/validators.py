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

    # Use singleton instance (managed identity) - works for all zones
    # NOTE: .for_zone() reserved for future multi-account support
    try:
        blob_repo = BlobRepository.instance()
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

    # Use singleton instance (managed identity) - works for all zones
    # NOTE: .for_zone() reserved for future multi-account support
    try:
        blob_repo = BlobRepository.instance()

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
# SIZE VALIDATION
# ============================================================================

@register_validator("blob_size_check")
def validate_blob_size(params: Dict[str, Any], config: Dict[str, Any]) -> ValidatorResult:
    """
    Validate blob size against configurable limits.

    Returns blob size in the result for downstream conditional logic.
    Size is stored in params['_blob_size_bytes'] for job use.

    Config options:
        container_param: str - Parameter name for container (default: 'container_name')
        blob_param: str - Parameter name for blob path (default: 'blob_name')
        max_size_mb: int - Maximum allowed size in MB (optional, no limit if not set)
        min_size_mb: int - Minimum required size in MB (optional, default 0)
        max_size_env: str - Environment variable for max size (overrides max_size_mb)
        error: str - Custom error message (optional)
        store_size: bool - Store size in params['_blob_size_bytes'] (default: True)

    Example:
        resource_validators = [
            {
                'type': 'blob_size_check',
                'container_param': 'container_name',
                'blob_param': 'blob_name',
                'max_size_mb': 5000,  # 5 GB limit
                'error': 'File too large for this job type'
            }
        ]

    Environment variable example:
        resource_validators = [
            {
                'type': 'blob_size_check',
                'max_size_env': 'MAX_RASTER_SIZE_MB',  # Read from env var
            }
        ]

    Size-based conditional example (in job):
        # After validation, size is available in params
        blob_size = params.get('_blob_size_bytes', 0)
        if blob_size > 1_000_000_000:  # > 1GB
            # Use chunked processing
        else:
            # Use in-memory processing
    """
    import os
    from infrastructure.blob import BlobRepository

    # Extract parameter names
    container_param = config.get('container_param', 'container_name')
    blob_param = config.get('blob_param', 'blob_name')
    store_size = config.get('store_size', True)

    container = params.get(container_param)
    blob_path = params.get(blob_param)

    if not container or not blob_path:
        return ValidatorResult(
            valid=False,
            message=f"Missing container or blob parameter for size check"
        )

    # Get size limits
    max_size_mb = config.get('max_size_mb')
    min_size_mb = config.get('min_size_mb', 0)

    # Check for environment variable override
    max_size_env = config.get('max_size_env')
    if max_size_env:
        env_value = os.environ.get(max_size_env)
        if env_value:
            try:
                max_size_mb = int(env_value)
            except ValueError:
                logger.warning(f"Invalid {max_size_env} value: {env_value}, ignoring")

    try:
        blob_repo = BlobRepository.instance()
        props = blob_repo.get_blob_properties(container, blob_path)
        size_bytes = props['size']
        size_mb = size_bytes / (1024 * 1024)

        # Store size in params for downstream use
        if store_size:
            params['_blob_size_bytes'] = size_bytes
            params['_blob_size_mb'] = size_mb

        logger.debug(f"📏 Pre-flight: blob size = {size_mb:.2f} MB ({container}/{blob_path})")

        # Check minimum size
        if min_size_mb and size_mb < min_size_mb:
            error_msg = config.get('error') or f"File too small: {size_mb:.2f} MB (minimum: {min_size_mb} MB)"
            logger.warning(f"❌ Pre-flight: {error_msg}")
            return ValidatorResult(valid=False, message=error_msg)

        # Check maximum size
        if max_size_mb and size_mb > max_size_mb:
            error_msg = config.get('error') or f"File too large: {size_mb:.2f} MB (maximum: {max_size_mb} MB)"
            logger.warning(f"❌ Pre-flight: {error_msg}")
            return ValidatorResult(valid=False, message=error_msg)

        logger.debug(f"✅ Pre-flight: blob size OK ({size_mb:.2f} MB)")
        return ValidatorResult(valid=True, message=None)

    except Exception as e:
        error_msg = f"Failed to check blob size: {e}"
        logger.error(error_msg)
        return ValidatorResult(valid=False, message=error_msg)


@register_validator("blob_list_exists")
def validate_blob_list_exists(params: Dict[str, Any], config: Dict[str, Any]) -> ValidatorResult:
    """
    Validate that ALL blobs in a list exist.

    This validator is designed for multi-tile workflows (e.g., raster collections)
    where all files must exist before job creation.

    Config options:
        container_param: str - Parameter name for container (default: 'container_name')
        blob_list_param: str - Parameter name for blob list (default: 'blob_list')
        skip_validation_param: str - Param that bypasses validation if True
                                     (default: '_skip_blob_validation')
        parallel: bool - Use parallel checking with ThreadPoolExecutor (default: True)
        max_parallel: int - Max concurrent checks (default: 10)
        report_all: bool - Report all missing blobs in error (default: True)
        min_count: int - Minimum number of blobs required (default: 2)
        error_not_found: str - Custom error message

    Stores in params:
        _blob_list_count: int - Number of blobs validated
        _blob_list_validated: bool - Whether validation was performed

    Example:
        resource_validators = [
            {
                'type': 'blob_list_exists',
                'container_param': 'container_name',
                'blob_list_param': 'blob_list',
                'skip_validation_param': '_skip_blob_validation',
                'parallel': True,
                'error_not_found': 'One or more tiles not found in collection'
            }
        ]

    Bypass Example (for trusted sources):
        job_params = {
            "blob_list": [...],
            "_skip_blob_validation": True  # Skips all blob existence checks
        }
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from infrastructure.blob import BlobRepository

    # Extract config options
    container_param = config.get('container_param', 'container_name')
    blob_list_param = config.get('blob_list_param', 'blob_list')
    skip_param = config.get('skip_validation_param', '_skip_blob_validation')
    use_parallel = config.get('parallel', True)
    max_parallel = config.get('max_parallel', 10)
    report_all = config.get('report_all', True)
    min_count = config.get('min_count', 2)

    # Check for bypass flag
    if params.get(skip_param, False):
        logger.info(f"⏭️ Pre-flight: blob_list validation bypassed ({skip_param}=True)")
        params['_blob_list_validated'] = False
        return ValidatorResult(valid=True, message=None)

    # Get container and blob list from params
    container = params.get(container_param)
    blob_list = params.get(blob_list_param)

    if not container:
        return ValidatorResult(
            valid=False,
            message=f"Container parameter '{container_param}' is missing or empty"
        )

    if not blob_list or not isinstance(blob_list, list):
        return ValidatorResult(
            valid=False,
            message=f"Blob list parameter '{blob_list_param}' must be a non-empty list"
        )

    if len(blob_list) < min_count:
        return ValidatorResult(
            valid=False,
            message=f"Collection must contain at least {min_count} files (got {len(blob_list)})"
        )

    try:
        blob_repo = BlobRepository.instance()

        # First check if container exists
        if not blob_repo.container_exists(container):
            error_msg = f"Container '{container}' does not exist"
            logger.warning(f"❌ Pre-flight: {error_msg}")
            return ValidatorResult(valid=False, message=error_msg)

        # Check all blobs exist
        missing_blobs = []

        def check_blob(blob_name: str) -> tuple:
            """Check single blob existence, return (blob_name, exists)."""
            exists = blob_repo.blob_exists(container, blob_name)
            return (blob_name, exists)

        if use_parallel and len(blob_list) > 1:
            # Parallel checking with ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=min(max_parallel, len(blob_list))) as executor:
                futures = {executor.submit(check_blob, blob): blob for blob in blob_list}
                for future in as_completed(futures):
                    blob_name, exists = future.result()
                    if not exists:
                        missing_blobs.append(blob_name)
                        if not report_all:
                            # Fast fail on first missing blob
                            break
        else:
            # Sequential checking
            for blob_name in blob_list:
                if not blob_repo.blob_exists(container, blob_name):
                    missing_blobs.append(blob_name)
                    if not report_all:
                        break

        # Store validation metadata
        params['_blob_list_count'] = len(blob_list)
        params['_blob_list_validated'] = True

        if missing_blobs:
            # Build error message
            if report_all:
                if len(missing_blobs) > 10:
                    missing_preview = missing_blobs[:10]
                    error_detail = (
                        f"{len(missing_blobs)} of {len(blob_list)} files not found:\n  - " +
                        "\n  - ".join(missing_preview) +
                        f"\n  ... and {len(missing_blobs) - 10} more"
                    )
                else:
                    error_detail = (
                        f"{len(missing_blobs)} of {len(blob_list)} files not found:\n  - " +
                        "\n  - ".join(missing_blobs)
                    )
            else:
                error_detail = f"File not found: {missing_blobs[0]}"

            error_msg = config.get('error_not_found') or error_detail
            logger.warning(f"❌ Pre-flight: {error_msg}")
            return ValidatorResult(valid=False, message=error_msg)

        logger.info(f"✅ Pre-flight: all {len(blob_list)} blobs exist in {container}")
        return ValidatorResult(valid=True, message=None)

    except Exception as e:
        error_msg = f"Failed to validate blob list: {e}"
        logger.error(error_msg)
        return ValidatorResult(valid=False, message=error_msg)


@register_validator("blob_exists_with_size")
def validate_blob_exists_with_size(params: Dict[str, Any], config: Dict[str, Any]) -> ValidatorResult:
    """
    Combined validator: Check blob exists AND get its size.

    This is more efficient than running blob_exists + blob_size_check separately
    as it makes a single API call. Size is stored in params['_blob_size_bytes'].

    Config options:
        container_param: str - Parameter for container name (default: 'container_name')
        blob_param: str - Parameter for blob path (default: 'blob_name')
        max_size_mb: int - Maximum allowed size in MB (optional)
        min_size_mb: int - Minimum required size in MB (optional)
        max_size_env: str - Environment variable for max size limit
        error_not_found: str - Error message if blob not found
        error_too_large: str - Error message if blob too large
        error_too_small: str - Error message if blob too small

    Example:
        resource_validators = [
            {
                'type': 'blob_exists_with_size',
                'container_param': 'container_name',
                'blob_param': 'blob_name',
                'max_size_mb': 10000,  # 10 GB
                'error_not_found': 'Source file not found in Bronze storage',
                'error_too_large': 'File exceeds 10GB limit for this job type'
            }
        ]
    """
    import os
    from infrastructure.blob import BlobRepository

    container_param = config.get('container_param', 'container_name')
    blob_param = config.get('blob_param', 'blob_name')

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

    # Get size limits
    max_size_mb = config.get('max_size_mb')
    min_size_mb = config.get('min_size_mb', 0)

    max_size_env = config.get('max_size_env')
    if max_size_env:
        env_value = os.environ.get(max_size_env)
        if env_value:
            try:
                max_size_mb = int(env_value)
            except ValueError:
                pass

    try:
        blob_repo = BlobRepository.instance()

        # First check if container/blob exist
        validation = blob_repo.validate_container_and_blob(container, blob_path)
        if not validation['valid']:
            error_msg = config.get('error_not_found') or validation['message']
            logger.warning(f"❌ Pre-flight: {error_msg}")
            return ValidatorResult(valid=False, message=error_msg)

        # Get properties (includes size)
        props = blob_repo.get_blob_properties(container, blob_path)
        size_bytes = props['size']
        size_mb = size_bytes / (1024 * 1024)

        # Store for downstream use
        params['_blob_size_bytes'] = size_bytes
        params['_blob_size_mb'] = size_mb
        params['_blob_content_type'] = props.get('content_type')
        params['_blob_last_modified'] = props.get('last_modified')

        logger.debug(f"📏 Pre-flight: blob exists, size = {size_mb:.2f} MB")

        # Check minimum size
        if min_size_mb and size_mb < min_size_mb:
            error_msg = config.get('error_too_small') or f"File too small: {size_mb:.2f} MB (minimum: {min_size_mb} MB)"
            logger.warning(f"❌ Pre-flight: {error_msg}")
            return ValidatorResult(valid=False, message=error_msg)

        # Check maximum size
        if max_size_mb and size_mb > max_size_mb:
            error_msg = config.get('error_too_large') or f"File too large: {size_mb:.2f} MB (maximum: {max_size_mb} MB)"
            logger.warning(f"❌ Pre-flight: {error_msg}")
            return ValidatorResult(valid=False, message=error_msg)

        logger.info(f"✅ Pre-flight: blob validated ({size_mb:.2f} MB)")
        return ValidatorResult(valid=True, message=None)

    except Exception as e:
        error_msg = f"Failed to validate blob: {e}"
        logger.error(error_msg)
        return ValidatorResult(valid=False, message=error_msg)


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
    'validate_blob_size',
    'validate_blob_list_exists',
    'validate_blob_exists_with_size',
]
