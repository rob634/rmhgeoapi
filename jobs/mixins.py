# ============================================================================
# CLAUDE CONTEXT - JOB BASE MIXIN (START HERE FOR NEW PIPELINES!)
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Core Infrastructure - Boilerplate elimination for job creation
# PURPOSE: Provides default implementations of repetitive job methods to reduce
#          new pipeline creation from 350 lines → 80 lines (77% reduction)
# LAST_REVIEWED: 14 NOV 2025
# EXPORTS: JobBaseMixin (inherit this for all new jobs!)
# INTERFACES: None (this IS the interface jobs should use)
# PYDANTIC_MODELS: Uses JobRecord, JobQueueMessage from core.models
# DEPENDENCIES: hashlib, json, uuid, infrastructure.RepositoryFactory
# SOURCE: Jobs inherit from this mixin to get default method implementations
# SCOPE: All job types - provides universal boilerplate elimination
# VALIDATION: Schema-based parameter validation (declarative)
# PATTERNS: Mixin pattern (multiple inheritance), Template Method pattern
# ENTRY_POINTS: class MyJob(JobBase, JobBaseMixin): ...
# INDEX:
#   - JobBaseMixin class definition: Line 75
#   - validate_job_parameters(): Line 145
#   - generate_job_id(): Line 280
#   - create_job_record(): Line 330
#   - queue_job(): Line 385
# ============================================================================

"""
JobBaseMixin - Default Implementations for Job Boilerplate

╔══════════════════════════════════════════════════════════════════════════╗
║                                                                          ║
║  🚀 START HERE FOR NEW GEOSPATIAL DATA PIPELINES! 🚀                    ║
║                                                                          ║
║  This mixin eliminates 185 lines of boilerplate per job.                ║
║  New pipelines: 30 minutes instead of 2 hours.                          ║
║                                                                          ║
╚══════════════════════════════════════════════════════════════════════════╝

═══════════════════════════════════════════════════════════════════════════
QUICK START: Create a New Pipeline in 5 Minutes
═══════════════════════════════════════════════════════════════════════════

Example: Process flood risk raster data

```python
# jobs/flood_risk_cog.py
from typing import List, Dict, Any
from jobs.base import JobBase
from jobs.mixins import JobBaseMixin

class FloodRiskCOGJob(JobBaseMixin, JobBase):  # ← Mixin FIRST!
    '''
    Process flood risk raster into Cloud Optimized GeoTIFFs (COGs).

    Pipeline: Validate → Create Tiles → Update STAC Catalog
    '''

    # ========================================================================
    # DECLARATIVE CONFIGURATION (No code!)
    # ========================================================================
    job_type = "flood_risk_cog"
    description = "Convert flood risk rasters to tiled COGs"

    stages = [
        {
            "number": 1,
            "name": "validate",
            "task_type": "validate_raster_file",
            "parallelism": "single"
        },
        {
            "number": 2,
            "name": "create_tiles",
            "task_type": "create_cog_tile",
            "parallelism": "fan_out"  # 1 file → N tiles
        },
        {
            "number": 3,
            "name": "update_catalog",
            "task_type": "update_stac_catalog",
            "parallelism": "single"
        }
    ]

    parameters_schema = {
        'dataset_id': {'type': 'str', 'required': True},
        'source_path': {'type': 'str', 'required': True},
        'tile_size': {'type': 'int', 'default': 256, 'allowed': [128, 256, 512]},
        'zoom_levels': {'type': 'int', 'default': 5, 'min': 1, 'max': 10}
    }

    # ========================================================================
    # PIPELINE-SPECIFIC LOGIC ONLY (~30 lines)
    # ========================================================================
    @staticmethod
    def create_tasks_for_stage(
        stage: int,
        job_params: dict,
        job_id: str,
        previous_results: list = None
    ) -> List[dict]:
        '''Generate tasks for each stage.'''

        if stage == 1:
            # Stage 1: Single validation task
            return [{
                "task_id": f"{job_id[:8]}-validate",
                "task_type": "validate_raster_file",
                "parameters": {
                    "source_path": job_params['source_path'],
                    "dataset_id": job_params['dataset_id']
                }
            }]

        elif stage == 2:
            # Stage 2: Fan-out based on file size from stage 1
            file_info = previous_results[0]['result']
            zoom_levels = range(10, 10 + job_params['zoom_levels'])

            return [
                {
                    "task_id": f"{job_id[:8]}-tile-z{zoom}",
                    "task_type": "create_cog_tile",
                    "parameters": {
                        "source_path": job_params['source_path'],
                        "zoom_level": zoom,
                        "tile_size": job_params['tile_size']
                    }
                }
                for zoom in zoom_levels
            ]

        elif stage == 3:
            # Stage 3: Update STAC catalog with all tiles
            tile_paths = [r['result']['tile_path'] for r in previous_results]
            return [{
                "task_id": f"{job_id[:8]}-stac",
                "task_type": "update_stac_catalog",
                "parameters": {
                    "dataset_id": job_params['dataset_id'],
                    "tile_paths": tile_paths
                }
            }]

    @staticmethod
    def finalize_job(context=None) -> Dict[str, Any]:
        '''Create final pipeline summary.'''
        if not context:
            return {"status": "completed", "job_type": "flood_risk_cog"}

        return {
            "status": "completed",
            "job_type": "flood_risk_cog",
            "tiles_created": len([r for r in context.task_results if 'tile' in r.task_type]),
            "total_tasks": len(context.task_results)
        }
```

That's it! JobBaseMixin provides:
✅ validate_job_parameters() - Schema-based validation (no code needed!)
✅ generate_job_id() - SHA256 hash generation (deterministic, idempotent)
✅ create_job_record() - Database persistence (atomic, idempotent)
✅ queue_job() - Service Bus message sending (reliable delivery)

═══════════════════════════════════════════════════════════════════════════
WHAT THIS MIXIN PROVIDES
═══════════════════════════════════════════════════════════════════════════

JobBaseMixin eliminates 4 repetitive methods (185 lines per job):

1. validate_job_parameters() - Schema-based parameter validation
   - Type checking (int, str, float, bool)
   - Range validation (min/max for numbers)
   - Enum validation (allowed values for strings)
   - Required vs optional with defaults
   - Example: {'n': {'type': 'int', 'min': 1, 'max': 100, 'default': 10}}

2. generate_job_id() - SHA256 hash from job_type + parameters
   - Deterministic (same params = same job_id)
   - Idempotent (duplicate submissions return existing job)
   - Includes job_type in hash (different job types can't collide)

3. create_job_record() - JobRecord creation and database persistence
   - Uses class attributes (job_type, stages, description)
   - PostgreSQL ON CONFLICT ensures idempotency
   - Sets initial status (QUEUED), stage (1), metadata

4. queue_job() - Service Bus message creation and sending
   - Creates JobQueueMessage with correlation_id
   - Sends to configured Service Bus jobs queue
   - Returns queue confirmation

═══════════════════════════════════════════════════════════════════════════
REQUIRED CLASS ATTRIBUTES
═══════════════════════════════════════════════════════════════════════════

Jobs inheriting from JobBaseMixin MUST define:

    job_type: str
        Unique identifier for this job type
        Example: "flood_risk_cog", "ingest_vector", "process_raster"

    description: str
        Human-readable description of what this job does
        Example: "Convert flood risk rasters to tiled COGs"

    stages: List[Dict[str, Any]]
        List of stage definitions (order matters - sequential execution)
        Example:
            [
                {
                    "number": 1,
                    "name": "validate",
                    "task_type": "validate_raster_file",
                    "parallelism": "single"
                },
                {
                    "number": 2,
                    "name": "create_tiles",
                    "task_type": "create_cog_tile",
                    "parallelism": "fan_out"
                }
            ]

    parameters_schema: Dict[str, Dict[str, Any]]
        Declarative parameter validation schema
        Supported types: 'int', 'str', 'float', 'bool'
        Supported constraints: 'required', 'default', 'min', 'max', 'allowed'
        Example:
            {
                'dataset_id': {'type': 'str', 'required': True},
                'tile_size': {'type': 'int', 'default': 256, 'min': 128, 'max': 512},
                'format': {'type': 'str', 'default': 'COG', 'allowed': ['COG', 'GeoTIFF']}
            }

═══════════════════════════════════════════════════════════════════════════
OVERRIDING MIXIN METHODS (Advanced - Only If Needed)
═══════════════════════════════════════════════════════════════════════════

The default implementations work for 95% of jobs. Override only when:

1. Custom job ID logic (e.g., exclude certain params from hash):
    @classmethod
    def generate_job_id(cls, params: dict) -> str:
        # Exclude 'failure_rate' from job ID hash (for testing)
        hash_params = {k: v for k, v in params.items() if k != 'failure_rate'}
        canonical = json.dumps({'job_type': cls.job_type, **hash_params}, sort_keys=True)
        return hashlib.sha256(canonical.encode('utf-8')).hexdigest()

2. Complex parameter validation (e.g., cross-field validation):
    @classmethod
    def validate_job_parameters(cls, params: dict) -> dict:
        # Call parent for basic validation
        validated = super().validate_job_parameters(params)

        # Add custom cross-field validation
        if validated['start_date'] > validated['end_date']:
            raise ValueError("start_date must be before end_date")

        return validated

3. Custom queue routing (e.g., priority queues):
    @classmethod
    def queue_job(cls, job_id: str, params: dict) -> dict:
        # Use priority queue for large datasets
        if params.get('priority') == 'high':
            queue_name = 'geospatial-jobs-priority'
        else:
            queue_name = config.service_bus_jobs_queue

        # ... rest of implementation (copy from mixin source)

═══════════════════════════════════════════════════════════════════════════
BENEFITS
═══════════════════════════════════════════════════════════════════════════

Before JobBaseMixin:
    - New job creation: ~350 lines, 2 hours
    - Boilerplate per job: 185 lines (53% of code)
    - Duplication across 10 jobs: ~1,850 lines of repeated code
    - Maintenance: Bug fixes require updating 10+ files

After JobBaseMixin:
    - New job creation: ~80 lines, 30 minutes (77% reduction!)
    - Boilerplate per job: 0 lines (provided by mixin)
    - Duplication: 150 lines (written once in mixin)
    - Maintenance: Bug fixes update 1 file, apply to all jobs

═══════════════════════════════════════════════════════════════════════════
SEE ALSO
═══════════════════════════════════════════════════════════════════════════

- JOB_CREATION_QUICKSTART.md - Step-by-step guide with examples
- jobs/hello_world.py - Reference implementation using JobBaseMixin
- COREMACHINE_CHANGE.md - Implementation plan and rationale
- jobs/base.py - JobBase abstract base class

═══════════════════════════════════════════════════════════════════════════

"""

from abc import ABC
from typing import Dict, Any
import hashlib
import json
import uuid


class JobBaseMixin(ABC):
    """
    Mixin providing default implementations of JobBase boilerplate methods.

    Inherit from this mixin to eliminate 185 lines of repetitive code per job.

    Usage:
        class MyJob(JobBaseMixin, JobBase):  # ← Mixin FIRST for correct MRO!
            job_type = "my_job"
            description = "What this job does"
            stages = [...]
            parameters_schema = {...}

            @staticmethod
            def create_tasks_for_stage(...):
                # Your unique pipeline logic here
                pass

            @staticmethod
            def finalize_job(context):
                # Your unique summary logic here
                pass

    Required Class Attributes:
        job_type: str - Unique job identifier
        description: str - Human-readable description
        stages: list - Stage definitions (dicts)
        parameters_schema: dict - Parameter validation schema

    Methods Provided:
        validate_job_parameters(params) -> dict
        generate_job_id(params) -> str
        create_job_record(job_id, params) -> dict
        queue_job(job_id, params) -> dict
    """

    # Subclasses MUST override these attributes
    # NOTE: Set to None to allow proper hasattr() checks
    # Subclasses MUST provide actual values or validation will fail
    job_type: str = None
    description: str = None
    stages: list = None
    parameters_schema: dict = None

    # ========================================================================
    # METHOD 1: validate_job_parameters() - Schema-based validation
    # ========================================================================

    @classmethod
    def validate_job_parameters(cls, params: dict) -> dict:
        """
        Default parameter validation using parameters_schema.

        Override for complex validation logic (cross-field validation, etc).

        Schema format:
            {
                'param_name': {
                    'type': 'int'|'str'|'float'|'bool'|'list',
                    'required': True|False,
                    'default': <value>,
                    'min': <number>,  # For int/float
                    'max': <number>,  # For int/float
                    'allowed': [...]  # For str (enum-like)
                }
            }

        Example:
            parameters_schema = {
                'dataset_id': {'type': 'str', 'required': True},
                'resolution': {'type': 'int', 'default': 10, 'min': 1, 'max': 100},
                'format': {'type': 'str', 'default': 'COG', 'allowed': ['COG', 'GeoTIFF']}
            }

        Args:
            params: Raw parameters from job submission

        Returns:
            Validated parameters with defaults applied

        Raises:
            ValueError: If validation fails
        """
        from util_logger import LoggerFactory, ComponentType

        logger = LoggerFactory.create_logger(
            ComponentType.CONTROLLER,
            f"{cls.__name__}.validate_job_parameters"
        )

        # Safety check: Ensure parameters_schema is defined
        if not hasattr(cls, 'parameters_schema') or cls.parameters_schema is None:
            raise AttributeError(
                f"{cls.__name__} must define 'parameters_schema' class attribute. "
                f"Example: parameters_schema = {{'param': {{'type': 'int', 'default': 10}}}}"
            )

        validated = {}

        for param_name, schema in cls.parameters_schema.items():
            # Get value from params or use default
            value = params.get(param_name, schema.get('default'))

            # Check required
            if value is None and schema.get('required', False):
                raise ValueError(f"Parameter '{param_name}' is required")

            # Skip validation if value is None and not required
            if value is None:
                continue

            # Type validation
            param_type = schema.get('type', 'str')
            if param_type == 'int':
                value = cls._validate_int(param_name, value, schema)
            elif param_type == 'float':
                value = cls._validate_float(param_name, value, schema)
            elif param_type == 'str':
                value = cls._validate_str(param_name, value, schema)
            elif param_type == 'bool':
                value = cls._validate_bool(param_name, value)
            elif param_type == 'list':
                value = cls._validate_list(param_name, value, schema)
            else:
                raise ValueError(f"Unknown type '{param_type}' for parameter '{param_name}'")

            validated[param_name] = value

        logger.debug(f"✅ Parameters validated: {list(validated.keys())}")
        return validated

    @staticmethod
    def _validate_int(param_name: str, value: Any, schema: dict) -> int:
        """Validate integer parameter."""
        if not isinstance(value, int):
            raise ValueError(
                f"Parameter '{param_name}' must be an integer, got {type(value).__name__}"
            )

        if 'min' in schema and value < schema['min']:
            raise ValueError(
                f"Parameter '{param_name}' must be >= {schema['min']}, got {value}"
            )

        if 'max' in schema and value > schema['max']:
            raise ValueError(
                f"Parameter '{param_name}' must be <= {schema['max']}, got {value}"
            )

        return value

    @staticmethod
    def _validate_float(param_name: str, value: Any, schema: dict) -> float:
        """Validate float parameter."""
        if not isinstance(value, (int, float)):
            raise ValueError(
                f"Parameter '{param_name}' must be a number, got {type(value).__name__}"
            )

        value = float(value)

        if 'min' in schema and value < schema['min']:
            raise ValueError(
                f"Parameter '{param_name}' must be >= {schema['min']}, got {value}"
            )

        if 'max' in schema and value > schema['max']:
            raise ValueError(
                f"Parameter '{param_name}' must be <= {schema['max']}, got {value}"
            )

        return value

    @staticmethod
    def _validate_str(param_name: str, value: Any, schema: dict) -> str:
        """Validate string parameter."""
        if not isinstance(value, str):
            raise ValueError(
                f"Parameter '{param_name}' must be a string, got {type(value).__name__}"
            )

        if 'allowed' in schema and value not in schema['allowed']:
            raise ValueError(
                f"Parameter '{param_name}' must be one of {schema['allowed']}, got '{value}'"
            )

        return value

    @staticmethod
    def _validate_bool(param_name: str, value: Any) -> bool:
        """Validate boolean parameter."""
        if not isinstance(value, bool):
            raise ValueError(
                f"Parameter '{param_name}' must be a boolean, got {type(value).__name__}"
            )
        return value

    @staticmethod
    def _validate_list(param_name: str, value: Any, schema: dict) -> list:
        """Validate list parameter."""
        if not isinstance(value, list):
            raise ValueError(
                f"Parameter '{param_name}' must be a list, got {type(value).__name__}"
            )
        return value

    # ========================================================================
    # METHOD 2: generate_job_id() - SHA256 hash generation
    # ========================================================================

    @classmethod
    def generate_job_id(cls, params: dict) -> str:
        """
        Default job ID generation (SHA256 of job_type + params).

        Override if you need custom ID logic (e.g., exclude certain params).

        Args:
            params: Validated job parameters

        Returns:
            SHA256 hash as hex string (64 characters)

        Example Override:
            @classmethod
            def generate_job_id(cls, params: dict) -> str:
                # Exclude 'failure_rate' from hash (for testing)
                hash_params = {k: v for k, v in params.items() if k != 'failure_rate'}
                canonical = json.dumps({
                    'job_type': cls.job_type,
                    **hash_params
                }, sort_keys=True)
                return hashlib.sha256(canonical.encode('utf-8')).hexdigest()
        """
        # Create canonical representation (includes job_type for uniqueness)
        canonical = json.dumps({
            'job_type': cls.job_type,
            **params
        }, sort_keys=True)

        # Generate SHA256 hash
        hash_obj = hashlib.sha256(canonical.encode('utf-8'))
        return hash_obj.hexdigest()

    # ========================================================================
    # METHOD 3: create_job_record() - JobRecord creation + DB persistence
    # ========================================================================

    @classmethod
    def create_job_record(cls, job_id: str, params: dict) -> dict:
        """
        Default job record creation and database persistence.

        Override if you need custom metadata or initialization.

        Args:
            job_id: Generated job ID from generate_job_id()
            params: Validated parameters from validate_job_parameters()

        Returns:
            Job record dict (from JobRecord.model_dump())

        Example Override:
            @classmethod
            def create_job_record(cls, job_id: str, params: dict) -> dict:
                # Call parent to get default record
                record_dict = super().create_job_record(job_id, params)

                # Add custom metadata
                record_dict['metadata']['custom_field'] = 'custom_value'

                return record_dict
        """
        from infrastructure import RepositoryFactory
        from core.models import JobRecord, JobStatus
        from util_logger import LoggerFactory, ComponentType

        logger = LoggerFactory.create_logger(
            ComponentType.CONTROLLER,
            f"{cls.__name__}.create_job_record"
        )

        # Create job record object
        job_record = JobRecord(
            job_id=job_id,
            job_type=cls.job_type,
            parameters=params,
            status=JobStatus.QUEUED,
            stage=1,
            total_stages=len(cls.stages),
            stage_results={},
            metadata={
                'description': cls.description,
                'created_by': cls.__name__
            }
        )

        logger.debug(f"💾 Creating job record: {job_id[:16]}...")

        # Persist to database
        repos = RepositoryFactory.create_repositories()
        job_repo = repos['job_repo']
        created = job_repo.create_job(job_record)

        if created:
            logger.info(f"✅ Job record created: {job_id[:16]}... (type={cls.job_type})")
        else:
            logger.info(f"📋 Job record already exists: {job_id[:16]}... (idempotent)")

        # Return as dict
        return job_record.model_dump()

    # ========================================================================
    # METHOD 4: queue_job() - Service Bus message sending
    # ========================================================================

    @classmethod
    def queue_job(cls, job_id: str, params: dict) -> dict:
        """
        Default job queueing to Service Bus.

        Override if you need custom queue routing or message properties.

        Args:
            job_id: Job ID
            params: Validated parameters

        Returns:
            Queue result information dict

        Example Override:
            @classmethod
            def queue_job(cls, job_id: str, params: dict) -> dict:
                # Use custom queue for priority jobs
                if params.get('priority') == 'high':
                    queue_name = 'geospatial-jobs-priority'
                else:
                    queue_name = config.service_bus_jobs_queue

                # ... rest of implementation
        """
        from infrastructure.service_bus import ServiceBusRepository
        from core.schema.queue import JobQueueMessage
        from config import get_config
        from util_logger import LoggerFactory, ComponentType

        logger = LoggerFactory.create_logger(
            ComponentType.CONTROLLER,
            f"{cls.__name__}.queue_job"
        )

        logger.info(f"🚀 Queueing {cls.job_type} job: {job_id[:16]}...")

        # Get config for queue name
        config = get_config()
        queue_name = config.service_bus_jobs_queue

        # Create Service Bus repository
        service_bus_repo = ServiceBusRepository()

        # Create job queue message
        job_message = JobQueueMessage(
            job_id=job_id,
            job_type=cls.job_type,
            stage=1,
            parameters=params,
            correlation_id=str(uuid.uuid4())[:8]
        )

        # Send to Service Bus jobs queue
        message_id = service_bus_repo.send_message(queue_name, job_message)

        logger.info(f"✅ Job queued: {job_id[:16]}... (message_id: {message_id})")

        return {
            "queued": True,
            "queue_type": "service_bus",
            "queue_name": queue_name,
            "message_id": message_id,
            "job_id": job_id
        }