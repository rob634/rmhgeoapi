# ============================================================================
# PLATFORM LAYER DATA MODELS - THIN TRACKING
# ============================================================================
# STATUS: Core - Anti-Corruption Layer (ACL) for DDH API
# PURPOSE: Translate DDH requests to CoreMachine with 1:1 job mapping
# LAST_REVIEWED: 03 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
Platform Layer Data Models - Thin Tracking Pattern.

Platform is an Anti-Corruption Layer (ACL) that translates DDH API to CoreMachine.
Uses thin tracking with 1:1 mapping: api_requests → job_id.

Architecture:
    - Platform translates DDH params → CoreMachine params
    - Creates ONE CoreMachine job per request
    - Stores request_id → job_id for DDH status lookups
    - No orchestration - CoreMachine handles job internals

Request ID Generation:
    SHA256(dataset_id + resource_id + version_id)[:32]
    Idempotent: same inputs = same ID

Exports:
    ApiRequest: Database model for request tracking
    PlatformRequest: DTO for incoming requests
    PlatformRequestStatus, DataType, OperationType: Enums
    - Natural deduplication of resubmitted requests

Database Tables Auto-Generated (stored in app schema with jobs/tasks):
    - app.api_requests (thin: request_id, DDH IDs, job_id, created_at)
    - NOTE: Platform tables live in app schema (not a separate platform schema)
    - This ensures api_requests is cleared during full-rebuild with other app tables

Removed (22 NOV 2025):
    - app.orchestration_jobs table (no job chaining)
    - OrchestrationJob model (moved to history)
    - jobs JSONB column (1:1 mapping now via job_id)
    - status column (delegate to CoreMachine)
    - metadata column (pass through, don't store twice)
"""

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Dict, Any, List, Optional, Union
from datetime import datetime
from enum import Enum
import logging
import re

from .stac import AccessLevel
from .processing_options import (
    BaseProcessingOptions,
    VectorProcessingOptions,
    RasterProcessingOptions,
    RasterCollectionProcessingOptions,
)

logger = logging.getLogger(__name__)

# Identifier character validation (18 FEB 2026)
# Alphanumeric, hyphens, underscores, dots. Must start with alphanumeric.
_IDENTIFIER_PATTERN = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._-]*$')


# ============================================================================
# ENUMS
# ============================================================================

class PlatformRequestStatus(str, Enum):
    """
    Platform request status enum.

    Note: With thin tracking, we mostly delegate status to CoreMachine.
    This enum is kept for backward compatibility and API responses.
    """
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class DataType(str, Enum):
    """
    Supported data types for processing.

    Used to determine which CoreMachine job to create.
    """
    RASTER = "raster"
    VECTOR = "vector"
    POINTCLOUD = "pointcloud"
    MESH_3D = "mesh_3d"
    TABULAR = "tabular"


class OperationType(str, Enum):
    """
    DDH operation types.

    CREATE is primary. UPDATE/DELETE are Phase 2.
    """
    CREATE = "CREATE"
    UPDATE = "UPDATE"  # Phase 2
    DELETE = "DELETE"  # Phase 2


# ============================================================================
# DATA TRANSFER OBJECTS (DTOs) - Not stored in database
# ============================================================================

class PlatformRequest(BaseModel):
    """
    Platform request from external application (DDH).

    This is a DTO (Data Transfer Object) for incoming HTTP requests.
    Accepts DDH API v1 format and gets translated to CoreMachine job parameters.

    The Platform layer validates this DTO, then uses PlatformConfig to:
    - Generate output naming (table names, folder paths, STAC IDs)
    - Validate container names and access levels
    - Create deterministic request_id from DDH identifiers

    Updated: 22 NOV 2025 - Simplified validation, delegate to PlatformConfig
    """

    # ========================================================================
    # DDH Core Identifiers (Required: dataset_id, resource_id; Optional: version_id)
    # ========================================================================
    # Character validation (18 FEB 2026): Reject at API boundary, not silently strip.
    # Allowed: a-z, A-Z, 0-9, hyphens, underscores, dots. NO spaces, #, &, ?, /, etc.
    # Downstream slugify functions convert to lowercase/specific formats, but the
    # raw input must be clean — prevents silent mangling and collision risk.
    dataset_id: str = Field(..., max_length=255, description="DDH dataset identifier")
    resource_id: str = Field(..., max_length=255, description="DDH resource identifier")
    version_id: Optional[str] = Field(
        default=None,
        max_length=50,
        description="DDH version identifier. Optional at submit (draft mode), required at approve."
    )

    # ========================================================================
    # V0.8 Release Control - Version Validation (31 JAN 2026)
    # ========================================================================
    # Required for subsequent versions to prevent race conditions.
    # Must match current latest version_id in the lineage.
    # See: docs_claude/DRY_RUN_IMPLEMENTATION.md
    previous_version_id: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Required for version advances. Must match current latest version_id in lineage."
    )

    @field_validator('dataset_id', 'resource_id', mode='after')
    @classmethod
    def validate_identifier_chars(cls, v: str, info) -> str:
        """
        Enforce safe characters for DDH identifiers.

        Allowed: alphanumeric, hyphens, underscores, dots.
        Must start with alphanumeric. Rejects at API boundary to prevent
        silent mangling by downstream slugify functions.
        """
        if not v or not v.strip():
            raise ValueError(f"{info.field_name} must not be empty or whitespace")
        v = v.strip()
        if not _IDENTIFIER_PATTERN.match(v):
            bad_chars = set(re.findall(r'[^a-zA-Z0-9._-]', v))
            raise ValueError(
                f"{info.field_name} contains invalid characters: {bad_chars}. "
                f"Allowed: letters, digits, hyphens, underscores, dots. "
                f"Must start with a letter or digit. Got: '{v}'"
            )
        return v

    @field_validator('version_id', 'previous_version_id', mode='after')
    @classmethod
    def validate_version_id_chars(cls, v: Optional[str], info) -> Optional[str]:
        """Validate version_id characters (same rules, but allows None)."""
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        if not _IDENTIFIER_PATTERN.match(v):
            bad_chars = set(re.findall(r'[^a-zA-Z0-9._-]', v))
            raise ValueError(
                f"{info.field_name} contains invalid characters: {bad_chars}. "
                f"Allowed: letters, digits, hyphens, underscores, dots. "
                f"Must start with a letter or digit. Got: '{v}'"
            )
        return v

    # ========================================================================
    # DDH Operation (Required)
    # ========================================================================
    operation: OperationType = Field(
        default=OperationType.CREATE,
        description="Operation type: CREATE/UPDATE/DELETE"
    )

    # ========================================================================
    # DDH File Information (Required)
    # ========================================================================
    container_name: str = Field(
        ...,
        max_length=100,
        description="Azure storage container name (e.g., bronze-vectors)"
    )
    file_name: Union[str, List[str]] = Field(
        ...,
        description="File name(s) - single string or array for raster collections"
    )

    # ========================================================================
    # DDH Service Metadata
    # ========================================================================
    title: Optional[str] = Field(
        None,
        max_length=255,
        description="Human-readable title for STAC item (optional - auto-generated from DDH IDs if not provided)"
    )
    # Classification enforcement (E4 Phase 1) - 26 JAN 2026
    # Accepts: "public" (any case), "OUO" or "Official Use Only" (any case)
    # Rejects: "restricted" (FUTURE - not yet supported), any other value
    access_level: AccessLevel = Field(
        default=AccessLevel.OUO,
        description="Data classification: 'public' or 'OUO'/'Official Use Only' (case insensitive)"
    )

    @field_validator('access_level', mode='before')
    @classmethod
    def normalize_access_level(cls, v):
        """
        Normalize and validate access_level input.

        Accepted values (case insensitive):
        - "public" → AccessLevel.PUBLIC
        - "ouo" or "official use only" → AccessLevel.OUO

        Rejected:
        - "restricted" → Not yet supported (future enhancement)
        - Anything else → Invalid

        Args:
            v: Input value (string or AccessLevel)

        Returns:
            AccessLevel enum value

        Raises:
            ValueError: If input is invalid or restricted
        """
        # Already an enum - pass through
        if isinstance(v, AccessLevel):
            # FUTURE: Remove this check when RESTRICTED is supported
            if v == AccessLevel.RESTRICTED:
                raise ValueError(
                    "access_level 'restricted' is not yet supported. "
                    "Use 'public' or 'OUO'. RESTRICTED support planned for future release."
                )
            return v

        # Must be string
        if not isinstance(v, str):
            raise ValueError(
                f"access_level must be a string. Got {type(v).__name__}. "
                "Valid values: 'public', 'OUO', 'Official Use Only'"
            )

        normalized = v.strip().lower()

        # Check for PUBLIC
        if normalized == "public":
            return AccessLevel.PUBLIC

        # Check for OUO (accepts "ouo" or "official use only")
        if normalized in ("ouo", "official use only"):
            return AccessLevel.OUO

        # FUTURE: RESTRICTED not yet supported
        if normalized == "restricted":
            raise ValueError(
                "access_level 'restricted' is not yet supported. "
                "Use 'public' or 'OUO'. RESTRICTED support planned for future release."
            )

        # Reject invalid values with helpful message
        raise ValueError(
            f"Invalid access_level '{v}'. "
            "Valid values: 'public', 'OUO', 'Official Use Only' (case insensitive)"
        )

    # ========================================================================
    # DDH Optional Metadata
    # ========================================================================
    description: Optional[str] = Field(None, description="Service description for API/STAC metadata")
    tags: List[str] = Field(default_factory=list, description="Tags for categorization/search")

    # ========================================================================
    # DDH Processing Options (Optional)
    # ========================================================================
    # Naming overrides (26 JAN 2026):
    #   - table_name: Custom PostGIS table name for vectors (slugified for PostgreSQL)
    #   - collection_id: Custom STAC collection ID for rasters
    # Other options: crs, nodata_value, overwrite, docker, lon_column, lat_column, etc.
    processing_options: Union[Dict[str, Any], BaseProcessingOptions] = Field(
        default_factory=dict,
        description="Processing options including table_name (vector) or collection_id (raster) overrides"
    )

    # ========================================================================
    # Client Identifier
    # ========================================================================
    client_id: str = Field(default="ddh", description="Client application identifier")

    # ========================================================================
    # Model Validator: Resolve processing_options to typed model
    # ========================================================================
    @model_validator(mode='after')
    def resolve_processing_options(self):
        """
        Dispatch raw dict processing_options to typed Pydantic model.

        Detects data_type from file_name extension, then parses the dict
        into VectorProcessingOptions, RasterProcessingOptions, or
        RasterCollectionProcessingOptions. From this point forward, all
        access is typed attribute access — no more .get().

        Unknown keys are logged and dropped (extra='ignore').
        """
        opts = self.processing_options
        # Already resolved (e.g., constructed programmatically)
        if isinstance(opts, BaseProcessingOptions):
            return self

        # Must be a dict (from JSON parsing)
        if not isinstance(opts, dict):
            self.processing_options = BaseProcessingOptions()
            return self

        raw_dict = opts

        # Log unknown keys that will be dropped
        try:
            data_type = self.data_type
        except ValueError:
            # Unsupported extension — use base model
            self.processing_options = BaseProcessingOptions(**raw_dict)
            return self

        if data_type == DataType.VECTOR:
            model_cls = VectorProcessingOptions
        elif data_type == DataType.RASTER:
            if self.is_raster_collection:
                model_cls = RasterCollectionProcessingOptions
            else:
                model_cls = RasterProcessingOptions
        else:
            # POINTCLOUD, MESH_3D, TABULAR — use base model
            model_cls = BaseProcessingOptions

        # Log keys that will be ignored
        known_fields = set(model_cls.model_fields.keys())
        unknown_keys = set(raw_dict.keys()) - known_fields
        if unknown_keys:
            logger.debug(f"Processing options: ignoring unknown keys {unknown_keys} for {model_cls.__name__}")

        self.processing_options = model_cls(**raw_dict)
        return self

    # ========================================================================
    # Computed Properties
    # ========================================================================

    # REMOVED (02 JAN 2026): source_location property
    # Was dead code with hardcoded storage account. Use zone-based storage:
    #   from infrastructure import RepositoryFactory
    #   blob_repo = RepositoryFactory.create_blob_repository(zone="bronze")
    #   url = blob_repo.get_blob_url(container, blob_path)

    @property
    def data_type(self) -> DataType:
        """
        Detect data type from file extension.

        Returns:
            DataType enum (RASTER, VECTOR, POINTCLOUD, MESH_3D, TABULAR)
        """
        # Get first file name if array
        file_name = self.file_name[0] if isinstance(self.file_name, list) else self.file_name

        # Extract extension
        ext = file_name.lower().split('.')[-1]

        # Map extension to data type
        if ext in ['geojson', 'gpkg', 'shp', 'zip', 'csv', 'gdb', 'kml', 'kmz']:
            return DataType.VECTOR
        elif ext in ['tif', 'tiff']:
            return DataType.RASTER
        elif ext == 'nc':
            raise ValueError(
                "NetCDF (.nc) support is under development. "
                "Currently only GeoTIFF (.tif, .tiff) files are accepted."
            )
        elif ext in ['img', 'hdf', 'hdf5', 'jp2', 'ecw', 'vrt', 'geotiff']:
            raise ValueError(
                f"Unsupported file format '.{ext}'. "
                f"Only GeoTIFF (.tif, .tiff) files are accepted."
            )
        elif ext in ['las', 'laz', 'e57']:
            return DataType.POINTCLOUD
        elif ext in ['obj', 'fbx', 'gltf', 'glb']:
            return DataType.MESH_3D
        elif ext in ['xlsx', 'parquet']:
            return DataType.TABULAR
        else:
            raise ValueError(f"Unsupported file format: {ext}")

    def validate_expected_data_type(self) -> None:
        """
        Validate that detected data_type matches expected_data_type if specified.

        Called explicitly after model creation to validate data type expectations.
        This catches mismatches like submitting a .geojson file when expecting raster.

        Raises:
            ValueError: If expected_data_type doesn't match detected data_type

        Example:
            request = PlatformRequest(**body)
            request.validate_expected_data_type()  # Raises if mismatch
        """
        expected = self.processing_options.expected_data_type
        if expected:
            expected_lower = expected.lower()
            detected = self.data_type.value.lower()
            if expected_lower != detected:
                file_name = self.file_name[0] if isinstance(self.file_name, list) else self.file_name
                raise ValueError(
                    f"Data type mismatch: file '{file_name}' detected as '{detected}' "
                    f"but expected_data_type='{expected}'. "
                    f"Check file extension or remove expected_data_type constraint."
                )

    @property
    def stac_item_id(self) -> str:
        """
        Generate URL-safe STAC item_id from DDH identifiers.

        Example: "aerial-imagery-2024", "site-alpha", "v1.0" → "aerial-imagery-2024_site-alpha_v1-0"
        Draft mode: "aerial-imagery-2024", "site-alpha", None → "aerial-imagery-2024_site-alpha_draft"

        ⚠️ PLACEHOLDER ONLY: This property uses "draft" because the version ordinal
        is not available on the request model. The authoritative STAC item ID is set
        by the submit trigger's finalization step (e.g. *_ord1). This property is
        only used for logging and dry_run responses.
        """
        # Build from DDH identifiers (same pattern as PlatformConfig)
        version_part = self.version_id if self.version_id else "draft"
        item_id = f"{self.dataset_id}_{self.resource_id}_{version_part}"
        item_id = item_id.lower()
        item_id = item_id.replace(' ', '-')
        item_id = re.sub(r'[^a-z0-9\-_]', '', item_id)
        return item_id

    @property
    def generated_title(self) -> str:
        """
        Get title for STAC metadata.

        Returns user-provided title if set, otherwise generates from DDH IDs.
        Example: "aerial-imagery-2024 / site-alpha v1.0"
        Draft mode: "aerial-imagery-2024 / site-alpha (draft)"
        """
        if self.title:
            return self.title
        version_part = self.version_id if self.version_id else "(draft)"
        return f"{self.dataset_id} / {self.resource_id} {version_part}"

    @property
    def is_raster_collection(self) -> bool:
        """Check if this is a raster collection request (multiple files)."""
        return (
            isinstance(self.file_name, list) and
            len(self.file_name) > 1 and
            self.data_type == DataType.RASTER
        )


# ============================================================================
# DATABASE MODELS - Thin Tracking (22 NOV 2025)
# ============================================================================

class ApiRequest(BaseModel):
    """
    API request database record - THIN TRACKING ONLY.

    ⚠️ SIMPLIFIED (22 NOV 2025): This is now a thin tracking layer.
    ⚠️ UPDATED (01 JAN 2026): Added retry_count and updated_at for failed job resubmission.
    ⚠️ UPDATED (30 JAN 2026 - V0.8 Release Control): Added asset_id and platform_id for linkage.

    Purpose:
        - Store DDH identifiers for status lookup
        - Map request_id → job_id (1:1)
        - Enable DDH to poll /api/platform/status/{request_id}
        - Platform looks up job_id, fetches status from CoreMachine
        - Track user-initiated retries of failed jobs (retry_count)
        - Track asset and platform linkage (V0.8 Release Control)

    What's REMOVED:
        - jobs JSONB (was: multi-job tracking)
        - status column (delegate to CoreMachine job status)
        - parameters JSONB (passed to CoreMachine, not stored twice)
        - metadata JSONB (passed to CoreMachine, not stored twice)
        - result_data JSONB (CoreMachine stores results)

    Auto-generates:
        CREATE TABLE app.api_requests (
            request_id VARCHAR(32) PRIMARY KEY,
            dataset_id VARCHAR(255) NOT NULL,
            resource_id VARCHAR(255) NOT NULL,
            version_id VARCHAR(50) NOT NULL,
            job_id VARCHAR(64) NOT NULL,
            data_type VARCHAR(50) NOT NULL,
            asset_id VARCHAR(64),  -- V0.8 Release Control
            platform_id VARCHAR(50),  -- V0.8 Release Control
            retry_count INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );

    Request ID Generation:
        SHA256(dataset_id | resource_id | version_id)[:32]
        - Idempotent: same DDH identifiers = same request_id
        - See config.generate_platform_request_id()

    Retry Tracking (01 JAN 2026):
        - retry_count: Increments when user resubmits a failed job
        - updated_at: Timestamp of last retry (or creation if never retried)
        - Distinguishes automated CoreMachine retries from user-initiated Platform retries
    """
    request_id: str = Field(
        ...,
        max_length=32,
        description="SHA256(dataset_id|resource_id|version_id)[:32] - idempotent"
    )
    dataset_id: str = Field(..., max_length=255, description="DDH dataset identifier")
    resource_id: str = Field(..., max_length=255, description="DDH resource identifier")
    version_id: str = Field(default="", max_length=50, description="DDH version identifier (empty string for drafts)")
    job_id: str = Field(
        ...,
        max_length=64,
        description="CoreMachine job ID (1:1 mapping)"
    )
    data_type: str = Field(..., max_length=50, description="Type of data: raster, vector, etc.")

    # V0.8 Release Control: Asset & Platform linkage (30 JAN 2026)
    # Links this request to the asset it created/updated
    asset_id: Optional[str] = Field(
        default=None,
        max_length=64,
        description="FK to geospatial_assets - the asset this request creates/updates"
    )
    platform_id: Optional[str] = Field(
        default=None,
        max_length=50,
        description="FK to platforms - identifies B2B platform that made request"
    )

    retry_count: int = Field(
        default=0,
        description="Number of user-initiated retries (0 = first submission)"
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp when request was created"
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp of last update (retry or creation)"
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database storage."""
        return {
            'request_id': self.request_id,
            'dataset_id': self.dataset_id,
            'resource_id': self.resource_id,
            'version_id': self.version_id,
            'job_id': self.job_id,
            'data_type': self.data_type,
            'asset_id': self.asset_id,
            'platform_id': self.platform_id,
            'retry_count': self.retry_count,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


# ============================================================================
# SCHEMA METADATA - Used by PydanticToSQL generator
# ============================================================================

# Table names (22 NOV 2025 - Simplified to single table)
PLATFORM_TABLE_NAMES = {
    'ApiRequest': 'api_requests'
    # OrchestrationJob table REMOVED - no job chaining in Platform
}

# Primary keys
PLATFORM_PRIMARY_KEYS = {
    'ApiRequest': ['request_id']
}

# Indexes
PLATFORM_INDEXES = {
    'ApiRequest': [
        ('job_id',),       # Lookup by CoreMachine job
        ('dataset_id',),   # DDH queries by dataset
        ('created_at',),   # Recent requests
    ]
}


# ============================================================================
# BACKWARD COMPATIBILITY - Deprecated exports (22 NOV 2025)
# ============================================================================

# OrchestrationJob is REMOVED - kept as comment for migration reference
# class OrchestrationJob was used for multi-job tracking per request
# This is no longer needed with thin tracking (1:1 request → job mapping)

# If old code imports OrchestrationJob, it will get ImportError
# This is intentional - forces migration to new pattern
