"""
Pre-Flight Resource Validators.

Registry of validation functions for checking external resource existence
BEFORE job creation. Prevents wasted resources for jobs that would fail.

Exports:
    RESOURCE_VALIDATORS: Registry of validator functions
    run_validators: Execute validators against job parameters
    validate_blob_exists: Check blob existence
    validate_container_exists: Check container existence
    validate_table_exists: Check PostGIS table existence
    validate_table_not_exists: Check PostGIS table does not exist
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
    params: Dict[str, Any],
    job_context: Optional[Dict[str, str]] = None
) -> ValidatorResult:
    """
    Run a list of resource validators against job parameters.

    Args:
        validators: List of validator configurations from job class
        params: Validated job parameters
        job_context: Optional context for verbose logging (07 DEC 2025)
            {
                "job_type": "process_raster_v2",
                "job_id": "abc123...",  # May be None before job creation
                "submission_endpoint": "/api/platform/submit"
            }

    Returns:
        ValidatorResult with 'valid' bool and 'message' str
        - valid=True if ALL validators pass
        - valid=False with message from FIRST failing validator

    Example:
        result = run_validators(cls.resource_validators, validated_params, job_context)
        if not result['valid']:
            raise ValueError(f"Pre-flight validation failed: {result['message']}")
    """
    import time
    from config import get_config

    start_time = time.time()
    config = get_config()
    debug_mode = config.debug_mode
    validators_run = []

    # Extract job context for logging
    job_type = job_context.get('job_type', 'unknown') if job_context else 'unknown'
    job_id = job_context.get('job_id') if job_context else None

    if debug_mode and job_context:
        logger.info(f"🔍 Pre-flight validation starting for {job_type}" +
                   (f" (job_id: {job_id[:8]}...)" if job_id else ""))

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
        validator_start = time.time()
        result = validator_fn(params, validator_config)
        validator_elapsed = round((time.time() - validator_start) * 1000, 1)

        validators_run.append({
            "type": validator_type,
            "elapsed_ms": validator_elapsed,
            "valid": result['valid']
        })

        if not result['valid']:
            # Enhance error message with job context in debug mode
            if debug_mode and job_context:
                enhanced_msg = f"{result['message']} (job_type: {job_type}"
                if job_id:
                    enhanced_msg += f", job_id: {job_id[:8]}..."
                enhanced_msg += ")"
                result = ValidatorResult(valid=False, message=enhanced_msg)

            total_elapsed = round((time.time() - start_time) * 1000, 1)
            logger.warning(f"❌ Pre-flight validation FAILED for {job_type}: {result['message']} "
                          f"(checked {len(validators_run)} validator(s) in {total_elapsed}ms)")
            return result

    # All validators passed - log summary in debug mode
    total_elapsed = round((time.time() - start_time) * 1000, 1)

    if debug_mode:
        # Build verbose success summary
        summary_parts = [f"✅ Pre-flight validation PASSED for {job_type}"]

        # Add source info if available
        container = params.get('container_name')
        blob = params.get('blob_name') or params.get('blob_list', [None])[0] if params.get('blob_list') else None
        if container and blob:
            size_mb = params.get('_blob_size_mb')
            size_str = f", {size_mb:.1f} MB" if size_mb else ""
            summary_parts.append(f"   Source: {container}/{blob}{size_str}")

        # Add destination info if available
        table_name = params.get('table_name')
        schema = params.get('schema', 'geo')
        if table_name:
            summary_parts.append(f"   Destination: {schema}.{table_name}")

        # Add validators summary
        validator_names = [v['type'] for v in validators_run]
        summary_parts.append(f"   Validators: {', '.join(validator_names)}")
        summary_parts.append(f"   Total time: {total_elapsed}ms")

        logger.info("\n".join(summary_parts))
    else:
        logger.debug(f"✅ Pre-flight: {len(validators_run)} validators passed in {total_elapsed}ms")

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
        default_container: str - Default container if param is None/empty.
                    Special values: 'bronze.vectors', 'bronze.rasters', 'silver.cogs'
                    resolve from config at runtime (09 DEC 2025)
        error: str - Optional custom error message

    Example:
        resource_validators = [
            {
                'type': 'blob_exists',
                'container_param': 'container_name',
                'blob_param': 'blob_name',
                'zone': 'bronze',
                'default_container': 'bronze.vectors',  # Resolves from config
                'error': 'Source file not found'
            }
        ]
    """
    from infrastructure.blob import BlobRepository
    from config import get_config

    # Extract parameter names from config
    container_param = config.get('container_param', 'container_name')
    blob_param = config.get('blob_param', 'blob_name')

    # Get actual values from job parameters
    container = params.get(container_param)
    blob_path = params.get(blob_param)

    # Resolve default container if not provided (09 DEC 2025)
    if not container:
        default_container = config.get('default_container')
        if default_container:
            app_config = get_config()
            # Handle config path resolution (e.g., 'bronze.vectors' -> config.storage.bronze.vectors)
            if default_container == 'bronze.vectors':
                container = app_config.storage.bronze.vectors
            elif default_container == 'bronze.rasters':
                container = app_config.storage.bronze.rasters
            elif default_container == 'silver.cogs':
                container = app_config.storage.silver.cogs
            else:
                # Use as literal container name
                container = default_container
            logger.debug(f"📦 Resolved default container: {default_container} -> {container}")

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

    # Get zone from config (default: bronze for input validation)
    zone = config.get('zone', 'bronze')
    try:
        blob_repo = BlobRepository.for_zone(zone)
        validation = blob_repo.validate_container_and_blob(container, blob_path)

        if validation['valid']:
            logger.debug(f"✅ Pre-flight: blob exists: {container}/{blob_path}")
            return ValidatorResult(valid=True, message=None)
        else:
            # Use specific message from BlobRepository (includes container/blob names)
            # Custom error is appended as context if provided
            specific_msg = validation['message']
            custom_error = config.get('error')
            if custom_error:
                error_msg = f"{specific_msg} ({custom_error})"
            else:
                error_msg = specific_msg
            logger.warning(f"❌ Pre-flight: {error_msg}")
            return ValidatorResult(valid=False, message=error_msg)

    except Exception as e:
        error_msg = f"Failed to validate blob existence for '{container}/{blob_path}': {e}"
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

    # Get zone from config (default: bronze for input validation)
    zone = config.get('zone', 'bronze')
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
        error_msg = f"Failed to validate container existence for '{container}': {e}"
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
        error_msg = f"Failed to validate table existence for '{schema}.{table_name}': {e}"
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

    # Check for environment variable override
    max_size_env = config.get('max_size_env')
    if max_size_env:
        env_value = os.environ.get(max_size_env)
        if env_value:
            try:
                max_size_mb = int(env_value)
            except ValueError:
                logger.warning(f"Invalid {max_size_env} value: {env_value}, ignoring")

    # Get zone from config (default: bronze for input validation)
    zone = config.get('zone', 'bronze')
    try:
        blob_repo = BlobRepository.for_zone(zone)
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
            error_msg = config.get('error') or f"File '{container}/{blob_path}' too small: {size_mb:.2f} MB (minimum: {min_size_mb} MB)"
            logger.warning(f"❌ Pre-flight: {error_msg}")
            return ValidatorResult(valid=False, message=error_msg)

        # Check maximum size
        if max_size_mb and size_mb > max_size_mb:
            error_msg = config.get('error') or f"File '{container}/{blob_path}' too large: {size_mb:.2f} MB (maximum: {max_size_mb} MB)"
            logger.warning(f"❌ Pre-flight: {error_msg}")
            return ValidatorResult(valid=False, message=error_msg)

        logger.debug(f"✅ Pre-flight: blob size OK ({size_mb:.2f} MB)")
        return ValidatorResult(valid=True, message=None)

    except Exception as e:
        error_msg = f"Failed to check blob size for '{container}/{blob_path}': {e}"
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

    # Get zone from config (default: bronze for input validation)
    zone = config.get('zone', 'bronze')
    try:
        blob_repo = BlobRepository.for_zone(zone)

        # First check if container exists
        if not blob_repo.container_exists(container):
            error_msg = f"Container '{container}' does not exist in {zone} zone"
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
        error_msg = f"Failed to validate blob list in container '{container}' ({len(blob_list) if blob_list else 0} files): {e}"
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

    # Get zone from config (default: bronze for input validation)
    zone = config.get('zone', 'bronze')
    try:
        blob_repo = BlobRepository.for_zone(zone)

        # First check if container/blob exist
        validation = blob_repo.validate_container_and_blob(container, blob_path)
        if not validation['valid']:
            # Use specific message from BlobRepository (includes container/blob names)
            # Custom error is appended as context if provided
            specific_msg = validation['message']
            custom_error = config.get('error_not_found')
            if custom_error:
                error_msg = f"{specific_msg} ({custom_error})"
            else:
                error_msg = specific_msg
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
            error_msg = config.get('error_too_small') or f"File '{container}/{blob_path}' too small: {size_mb:.2f} MB (minimum: {min_size_mb} MB)"
            logger.warning(f"❌ Pre-flight: {error_msg}")
            return ValidatorResult(valid=False, message=error_msg)

        # Check maximum size
        if max_size_mb and size_mb > max_size_mb:
            error_msg = config.get('error_too_large') or f"File '{container}/{blob_path}' too large: {size_mb:.2f} MB (maximum: {max_size_mb} MB)"
            logger.warning(f"❌ Pre-flight: {error_msg}")
            return ValidatorResult(valid=False, message=error_msg)

        logger.info(f"✅ Pre-flight: blob validated ({size_mb:.2f} MB)")
        return ValidatorResult(valid=True, message=None)

    except Exception as e:
        error_msg = f"Failed to validate blob '{container}/{blob_path}': {e}"
        logger.error(error_msg)
        return ValidatorResult(valid=False, message=error_msg)


# ============================================================================
# RASTER COLLECTION SIZE VALIDATION (13 DEC 2025)
# ============================================================================

@register_validator("blob_list_exists_with_max_size")
def validate_blob_list_exists_with_max_size(
    params: Dict[str, Any],
    config: Dict[str, Any]
) -> ValidatorResult:
    """
    Validate all blobs in list exist AND capture max/total sizes.

    Combines blob_list_exists + blob_exists_with_size for efficiency:
    - Single API call per blob (get_blob_properties includes existence)
    - Parallel checking with ThreadPoolExecutor
    - Tracks max size for routing decisions (large files → Docker worker)

    Config options:
        container_param: str - Parameter for container (default: 'container_name')
        blob_list_param: str - Parameter for blob list (default: 'blob_list')
        skip_validation_param: str - Bypass flag (default: '_skip_blob_validation')
        parallel: bool - Use parallel checking (default: True)
        max_parallel: int - Max concurrent workers (default: 10)
        report_all: bool - Report all missing vs first (default: True)
        min_count: int - Minimum blobs required (default: 2)
        max_collection_count: int - Max files allowed in collection (optional)
        max_collection_count_env: str - Env var for collection limit (e.g., 'RASTER_COLLECTION_SIZE_LIMIT')
        max_individual_size_mb: int - Reject if ANY blob exceeds this (optional)
        max_individual_size_mb_env: str - Env var for size threshold (e.g., 'RASTER_SIZE_THRESHOLD_MB')
        error_not_found: str - Error if blob missing
        error_collection_too_large: str - Error if collection exceeds file count limit
        error_raster_too_large: str - Error if any blob exceeds size threshold

    Stores in params:
        _blob_list_count: int - Total blobs
        _blob_list_validated: bool - Whether validation occurred
        _blob_list_max_size_bytes: int - Largest blob size
        _blob_list_max_size_mb: float - Largest blob in MB
        _blob_list_total_size_bytes: int - Sum of all blobs
        _blob_list_total_size_mb: float - Sum in MB
        _blob_list_has_large_raster: bool - True if any blob > threshold
        _blob_list_largest_blob: str - Name of largest blob

    Example:
        resource_validators = [
            {
                'type': 'blob_list_exists_with_max_size',
                'container_param': 'container_name',
                'blob_list_param': 'blob_list',
                'max_collection_count_env': 'RASTER_COLLECTION_SIZE_LIMIT',
                'max_individual_size_mb_env': 'RASTER_SIZE_THRESHOLD_MB',
                'error_collection_too_large': 'Collection exceeds max file count.',
                'error_raster_too_large': 'Collection contains raster(s) exceeding size threshold.'
            }
        ]
    """
    import os
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
        logger.info(f"⏭️ Pre-flight: blob_list_exists_with_max_size bypassed ({skip_param}=True)")
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

    # Get collection count limit (from config or env var)
    max_collection_count = config.get('max_collection_count')
    max_collection_count_env = config.get('max_collection_count_env')
    if max_collection_count_env:
        env_value = os.environ.get(max_collection_count_env)
        if env_value:
            try:
                max_collection_count = int(env_value)
            except ValueError:
                logger.warning(f"Invalid {max_collection_count_env} value: {env_value}, ignoring")

    # Check collection count limit FIRST (before any blob API calls)
    if max_collection_count and len(blob_list) > max_collection_count:
        error_template = config.get('error_collection_too_large') or \
            f"Collection exceeds maximum file count ({max_collection_count} files). Submit smaller batches."
        # Support {limit} placeholder in error message
        error_msg = error_template.replace('{limit}', str(max_collection_count))
        logger.warning(f"❌ Pre-flight: {error_msg}")
        return ValidatorResult(valid=False, message=error_msg)

    # Get individual size threshold (from config or env var)
    max_individual_size_mb = config.get('max_individual_size_mb')
    max_individual_size_mb_env = config.get('max_individual_size_mb_env')
    if max_individual_size_mb_env:
        env_value = os.environ.get(max_individual_size_mb_env)
        if env_value:
            try:
                max_individual_size_mb = int(env_value)
            except ValueError:
                logger.warning(f"Invalid {max_individual_size_mb_env} value: {env_value}, ignoring")

    # Get zone from config (default: bronze for input validation)
    zone = config.get('zone', 'bronze')

    try:
        blob_repo = BlobRepository.for_zone(zone)

        # First check if container exists
        if not blob_repo.container_exists(container):
            error_msg = f"Container '{container}' does not exist in {zone} zone"
            logger.warning(f"❌ Pre-flight: {error_msg}")
            return ValidatorResult(valid=False, message=error_msg)

        # Track sizes and missing blobs
        blob_sizes = {}
        max_size_bytes = 0
        max_size_blob = None
        total_size_bytes = 0
        missing_or_failed = []
        large_rasters = []

        def get_blob_size(blob_name: str) -> tuple:
            """Get blob size, return (blob_name, size_bytes, exists, error)."""
            try:
                props = blob_repo.get_blob_properties(container, blob_name)
                return (blob_name, props['size'], True, None)
            except Exception as e:
                # Check if it's a "not found" type error
                error_str = str(e).lower()
                if 'not found' in error_str or 'does not exist' in error_str or '404' in error_str:
                    return (blob_name, None, False, "not found")
                return (blob_name, None, False, str(e))

        if use_parallel and len(blob_list) > 1:
            # Parallel checking with ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=min(max_parallel, len(blob_list))) as executor:
                futures = {executor.submit(get_blob_size, blob): blob for blob in blob_list}
                for future in as_completed(futures):
                    blob_name, size_bytes, exists, error = future.result()
                    if not exists or error:
                        missing_or_failed.append((blob_name, error or "not found"))
                        if not report_all:
                            break
                    else:
                        blob_sizes[blob_name] = size_bytes
                        total_size_bytes += size_bytes
                        if size_bytes > max_size_bytes:
                            max_size_bytes = size_bytes
                            max_size_blob = blob_name
                        # Check individual size threshold
                        if max_individual_size_mb:
                            size_mb = size_bytes / (1024 * 1024)
                            if size_mb > max_individual_size_mb:
                                large_rasters.append((blob_name, size_mb))
        else:
            # Sequential checking
            for blob_name in blob_list:
                bn, size_bytes, exists, error = get_blob_size(blob_name)
                if not exists or error:
                    missing_or_failed.append((blob_name, error or "not found"))
                    if not report_all:
                        break
                else:
                    blob_sizes[blob_name] = size_bytes
                    total_size_bytes += size_bytes
                    if size_bytes > max_size_bytes:
                        max_size_bytes = size_bytes
                        max_size_blob = blob_name
                    # Check individual size threshold
                    if max_individual_size_mb:
                        size_mb = size_bytes / (1024 * 1024)
                        if size_mb > max_individual_size_mb:
                            large_rasters.append((blob_name, size_mb))

        # Check for missing blobs first
        if missing_or_failed:
            if report_all:
                if len(missing_or_failed) > 10:
                    missing_preview = [m[0] for m in missing_or_failed[:10]]
                    error_detail = (
                        f"{len(missing_or_failed)} of {len(blob_list)} files not found:\n  - " +
                        "\n  - ".join(missing_preview) +
                        f"\n  ... and {len(missing_or_failed) - 10} more"
                    )
                else:
                    error_detail = (
                        f"{len(missing_or_failed)} of {len(blob_list)} files not found:\n  - " +
                        "\n  - ".join([m[0] for m in missing_or_failed])
                    )
            else:
                error_detail = f"File not found: {missing_or_failed[0][0]}"

            error_msg = config.get('error_not_found') or error_detail
            logger.warning(f"❌ Pre-flight: {error_msg}")
            return ValidatorResult(valid=False, message=error_msg)

        # Check for large rasters (after all sizes are collected)
        if large_rasters:
            largest = max(large_rasters, key=lambda x: x[1])
            error_template = config.get('error_raster_too_large') or \
                f"Collection contains raster(s) exceeding {max_individual_size_mb}MB threshold. " \
                f"Largest: {largest[0]} ({largest[1]:.1f}MB). " \
                "Large raster collection processing requires Docker worker (coming soon)."
            # Support {threshold} placeholder
            error_msg = error_template.replace('{threshold}', str(max_individual_size_mb))
            logger.warning(f"❌ Pre-flight: {error_msg}")
            return ValidatorResult(valid=False, message=error_msg)

        # Success - store size information
        max_size_mb = max_size_bytes / (1024 * 1024)
        total_size_mb = total_size_bytes / (1024 * 1024)

        params['_blob_list_count'] = len(blob_list)
        params['_blob_list_validated'] = True
        params['_blob_list_max_size_bytes'] = max_size_bytes
        params['_blob_list_max_size_mb'] = max_size_mb
        params['_blob_list_total_size_bytes'] = total_size_bytes
        params['_blob_list_total_size_mb'] = total_size_mb
        params['_blob_list_largest_blob'] = max_size_blob
        params['_blob_list_has_large_raster'] = False  # All under threshold

        logger.info(
            f"✅ Pre-flight: {len(blob_list)} blobs validated "
            f"(max={max_size_mb:.1f}MB, total={total_size_mb:.1f}MB)"
        )
        return ValidatorResult(valid=True, message=None)

    except Exception as e:
        error_msg = f"Failed to validate blob list in container '{container}' ({len(blob_list) if blob_list else 0} files): {e}"
        logger.error(error_msg)
        return ValidatorResult(valid=False, message=error_msg)


# ============================================================================
# STAC VALIDATORS (12 DEC 2025 - Unpublish Workflow Support)
# ============================================================================

@register_validator("stac_item_exists")
def validate_stac_item_exists(params: Dict[str, Any], config: Dict[str, Any]) -> ValidatorResult:
    """
    Validate that a STAC item exists in pgstac.items.

    This validator is essential for unpublish workflows - prevents
    attempting to delete items that don't exist.

    Stores the full STAC item content in params['_stac_item'] for
    downstream use (audit trail, artifact lookup).

    Config options:
        item_id_param: str - Parameter name for STAC item ID (default: 'stac_item_id')
        collection_id_param: str - Parameter name for collection ID (default: 'collection_id')
        store_item: bool - Store full item in params['_stac_item'] (default: True)
        error: str - Optional custom error message

    Example:
        resource_validators = [
            {
                'type': 'stac_item_exists',
                'item_id_param': 'stac_item_id',
                'collection_id_param': 'collection_id',
                'error': 'STAC item not found - cannot unpublish'
            }
        ]

    Stored in params (if store_item=True):
        _stac_item: dict - Full STAC item content (for audit trail)
        _stac_item_assets: dict - Item assets (for blob deletion)
        _stac_original_job_id: str - Original processing job ID (if available)
    """
    from infrastructure.postgresql import PostgreSQLRepository

    item_id_param = config.get('item_id_param', 'stac_item_id')
    collection_id_param = config.get('collection_id_param', 'collection_id')
    store_item = config.get('store_item', True)

    item_id = params.get(item_id_param)
    collection_id = params.get(collection_id_param)

    if not item_id:
        return ValidatorResult(
            valid=False,
            message=f"STAC item ID parameter '{item_id_param}' is missing or empty"
        )

    if not collection_id:
        return ValidatorResult(
            valid=False,
            message=f"Collection ID parameter '{collection_id_param}' is missing or empty"
        )

    try:
        repo = PostgreSQLRepository()
        with repo._get_connection() as conn:
            with conn.cursor() as cur:
                # Query pgstac.items for the item
                # pgstac stores: id, collection, geometry, content (JSONB)
                cur.execute(
                    """
                    SELECT id, collection, content
                    FROM pgstac.items
                    WHERE id = %s AND collection = %s
                    """,
                    (item_id, collection_id)
                )
                result = cur.fetchone()

        if result:
            logger.debug(f"✅ Pre-flight: STAC item exists: {collection_id}/{item_id}")

            if store_item:
                # Store full item for downstream use
                content = result['content'] if isinstance(result, dict) else result[2]
                params['_stac_item'] = content

                # Extract assets for blob deletion
                if isinstance(content, dict):
                    params['_stac_item_assets'] = content.get('assets', {})

                    # Extract original job ID if available (for idempotency fix)
                    properties = content.get('properties', {})
                    original_job_id = properties.get('processing:job_id') or properties.get('etl_job_id')
                    if original_job_id:
                        params['_stac_original_job_id'] = original_job_id

            return ValidatorResult(valid=True, message=None)
        else:
            error_msg = config.get('error') or f"STAC item '{item_id}' not found in collection '{collection_id}'"
            logger.warning(f"❌ Pre-flight: {error_msg}")
            return ValidatorResult(valid=False, message=error_msg)

    except Exception as e:
        error_msg = f"Failed to validate STAC item existence for '{collection_id}/{item_id}': {e}"
        logger.error(error_msg)
        return ValidatorResult(valid=False, message=error_msg)


@register_validator("stac_collection_exists")
def validate_stac_collection_exists(params: Dict[str, Any], config: Dict[str, Any]) -> ValidatorResult:
    """
    Validate that a STAC collection exists in pgstac.collections.

    Config options:
        collection_id_param: str - Parameter name for collection ID (default: 'collection_id')
        store_collection: bool - Store collection in params['_stac_collection'] (default: False)
        error: str - Optional custom error message

    Example:
        resource_validators = [
            {
                'type': 'stac_collection_exists',
                'collection_id_param': 'collection_id',
                'error': 'STAC collection does not exist'
            }
        ]
    """
    from infrastructure.postgresql import PostgreSQLRepository

    collection_id_param = config.get('collection_id_param', 'collection_id')
    store_collection = config.get('store_collection', False)

    collection_id = params.get(collection_id_param)

    if not collection_id:
        return ValidatorResult(
            valid=False,
            message=f"Collection ID parameter '{collection_id_param}' is missing or empty"
        )

    try:
        repo = PostgreSQLRepository()
        with repo._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, content
                    FROM pgstac.collections
                    WHERE id = %s
                    """,
                    (collection_id,)
                )
                result = cur.fetchone()

        if result:
            logger.debug(f"✅ Pre-flight: STAC collection exists: {collection_id}")

            if store_collection:
                content = result['content'] if isinstance(result, dict) else result[1]
                params['_stac_collection'] = content

            return ValidatorResult(valid=True, message=None)
        else:
            error_msg = config.get('error') or f"STAC collection '{collection_id}' does not exist"
            logger.warning(f"❌ Pre-flight: {error_msg}")
            return ValidatorResult(valid=False, message=error_msg)

    except Exception as e:
        error_msg = f"Failed to validate STAC collection existence for '{collection_id}': {e}"
        logger.error(error_msg)
        return ValidatorResult(valid=False, message=error_msg)


@register_validator("stac_item_not_exists")
def validate_stac_item_not_exists(params: Dict[str, Any], config: Dict[str, Any]) -> ValidatorResult:
    """
    Validate that a STAC item does NOT exist (for create-new workflows).

    Useful for ensuring idempotency - prevent duplicate item creation.

    Config options:
        item_id_param: str - Parameter name for STAC item ID (default: 'stac_item_id')
        collection_id_param: str - Parameter name for collection ID (default: 'collection_id')
        allow_overwrite_param: str - If this param is True, skip validation
        error: str - Optional custom error message

    Example:
        resource_validators = [
            {
                'type': 'stac_item_not_exists',
                'item_id_param': 'stac_item_id',
                'collection_id_param': 'collection_id',
                'allow_overwrite_param': 'overwrite',
                'error': 'STAC item already exists. Set overwrite=true to replace.'
            }
        ]
    """
    # Check if overwrite is allowed
    allow_overwrite_param = config.get('allow_overwrite_param')
    if allow_overwrite_param and params.get(allow_overwrite_param):
        logger.debug(f"✅ Pre-flight: stac_item_not_exists skipped (overwrite={params.get(allow_overwrite_param)})")
        return ValidatorResult(valid=True, message=None)

    # Inverse of stac_item_exists
    result = validate_stac_item_exists(params, {**config, 'store_item': False})

    if result['valid']:
        # Item exists - this is a FAILURE for stac_item_not_exists
        item_id_param = config.get('item_id_param', 'stac_item_id')
        collection_id_param = config.get('collection_id_param', 'collection_id')
        item_id = params.get(item_id_param)
        collection_id = params.get(collection_id_param)

        error_msg = config.get('error') or f"STAC item '{item_id}' already exists in collection '{collection_id}'"
        return ValidatorResult(valid=False, message=error_msg)
    else:
        # Item doesn't exist - this is SUCCESS for stac_item_not_exists
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
    'validate_blob_size',
    'validate_blob_list_exists',
    'validate_blob_exists_with_size',
    # Collection size validation (13 DEC 2025)
    'validate_blob_list_exists_with_max_size',
    # STAC validators (12 DEC 2025)
    'validate_stac_item_exists',
    'validate_stac_collection_exists',
    'validate_stac_item_not_exists',
]
