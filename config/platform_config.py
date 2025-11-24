# ============================================================================
# CLAUDE CONTEXT - PLATFORM CONFIGURATION
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: New module - Platform layer configuration (22 NOV 2025)
# PURPOSE: DDH integration and Platform layer configuration
# LAST_REVIEWED: 22 NOV 2025
# EXPORTS: PlatformConfig, generate_platform_request_id
# INTERFACES: Pydantic BaseModel
# PYDANTIC_MODELS: PlatformConfig
# DEPENDENCIES: pydantic, os, hashlib, re
# SOURCE: Environment variables (PLATFORM_*)
# SCOPE: Platform layer (DDH integration, anti-corruption layer)
# VALIDATION: Pydantic v2 validation
# PATTERNS: Value objects, factory methods, idempotent ID generation
# ENTRY_POINTS: from config import PlatformConfig, generate_platform_request_id
# INDEX: PlatformConfig:60, generate_platform_request_id:180
# ============================================================================

"""
Platform Layer Configuration - DDH Integration Anti-Corruption Layer

This module provides configuration for the Platform layer which acts as an
Anti-Corruption Layer (ACL) between DDH (Data Discovery Hub) and CoreMachine.

Architecture:
    DDH (external, unstable API) → Platform (translator) → CoreMachine (internal, stable)

Key Responsibilities:
    1. Translate DDH identifiers to CoreMachine parameters
    2. Generate deterministic output paths from DDH IDs
    3. Validate DDH input containers and access levels
    4. Define URL patterns for vector tables, raster collections, STAC items

DDH Core Identifiers:
    - dataset_id: Top-level organizational unit (e.g., "aerial-imagery-2024")
    - resource_id: Second-level identifier (e.g., "site-alpha")
    - version_id: Version control (e.g., "v1.0", "2024-10-29")

    Combined: SHA256(dataset_id + resource_id + version_id)[:32] = idempotent request_id

Created: 22 NOV 2025
Author: Robert and Geospatial Claude Legion
"""

import os
import re
import hashlib
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


# ============================================================================
# PLATFORM CONFIGURATION
# ============================================================================

class PlatformConfig(BaseModel):
    """
    Platform layer configuration for DDH integration.

    The Platform layer is an Anti-Corruption Layer (ACL) that:
    - Accepts DDH-specific identifiers (dataset_id, resource_id, version_id)
    - Translates them to CoreMachine parameters (table_name, collection_id, blob_name)
    - Provides stable internal API while DDH API may change during integration

    This design allows DDH API changes to be absorbed in Platform without
    touching CoreMachine job implementations.
    """

    # ========================================================================
    # Client Configuration
    # ========================================================================

    primary_client: str = Field(
        default="ddh",
        description="Primary client application identifier",
        examples=["ddh", "analytics", "mobile"]
    )

    # ========================================================================
    # Valid Input Containers (DDH Bronze Tier)
    # ========================================================================

    valid_input_containers: List[str] = Field(
        default=[
            "bronze-vectors",
            "bronze-rasters",
            "bronze-misc",
            "bronze-temp",
            "rmhazuregeobronze"  # Legacy flat container
        ],
        description="Valid Azure containers for DDH input data (Bronze tier)"
    )

    # ========================================================================
    # Access Levels (for future APIM enforcement)
    # ========================================================================

    valid_access_levels: List[str] = Field(
        default=["public", "OUO", "restricted"],
        description="Valid access level values for DDH data"
    )

    default_access_level: str = Field(
        default="OUO",
        description="Default access level if not specified by DDH"
    )

    # ========================================================================
    # Output Naming Patterns
    # ========================================================================
    # These patterns define how DDH identifiers map to CoreMachine output names

    vector_table_pattern: str = Field(
        default="{dataset_id}_{resource_id}_{version_id}",
        description="Pattern for PostGIS table names from DDH identifiers. "
                    "Placeholders: {dataset_id}, {resource_id}, {version_id}"
    )

    raster_output_folder_pattern: str = Field(
        default="{dataset_id}/{resource_id}/{version_id}",
        description="Pattern for COG output folder paths. "
                    "Placeholders: {dataset_id}, {resource_id}, {version_id}"
    )

    stac_collection_pattern: str = Field(
        default="{dataset_id}",
        description="Pattern for STAC collection IDs. "
                    "Placeholders: {dataset_id}, {resource_id}, {version_id}"
    )

    stac_item_pattern: str = Field(
        default="{dataset_id}_{resource_id}_{version_id}",
        description="Pattern for STAC item IDs (URL-safe slugified). "
                    "Placeholders: {dataset_id}, {resource_id}, {version_id}"
    )

    # ========================================================================
    # Request ID Configuration
    # ========================================================================

    request_id_length: int = Field(
        default=32,
        ge=16,
        le=64,
        description="Length of generated request IDs (SHA256 hash prefix)"
    )

    # ========================================================================
    # Webhook Configuration (Future)
    # ========================================================================

    webhook_enabled: bool = Field(
        default=False,
        description="Enable webhook callbacks to DDH on job completion"
    )

    webhook_retry_count: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Number of retry attempts for failed webhook deliveries"
    )

    webhook_retry_delay_seconds: int = Field(
        default=5,
        ge=1,
        le=300,
        description="Base delay between webhook retry attempts (exponential backoff)"
    )

    # ========================================================================
    # Validators
    # ========================================================================

    @field_validator('vector_table_pattern', 'raster_output_folder_pattern',
                     'stac_collection_pattern', 'stac_item_pattern')
    @classmethod
    def validate_pattern_has_placeholders(cls, v: str) -> str:
        """Ensure patterns contain at least one valid placeholder."""
        valid_placeholders = ['{dataset_id}', '{resource_id}', '{version_id}']
        if not any(p in v for p in valid_placeholders):
            raise ValueError(
                f"Pattern must contain at least one placeholder: {valid_placeholders}"
            )
        return v

    # ========================================================================
    # Factory Methods
    # ========================================================================

    @classmethod
    def from_environment(cls) -> 'PlatformConfig':
        """Load from environment variables."""

        # Parse valid containers from comma-separated list
        containers_env = os.environ.get(
            "PLATFORM_VALID_CONTAINERS",
            "bronze-vectors,bronze-rasters,bronze-misc,bronze-temp,rmhazuregeobronze"
        )
        valid_containers = [c.strip() for c in containers_env.split(",") if c.strip()]

        # Parse access levels from comma-separated list
        access_env = os.environ.get("PLATFORM_ACCESS_LEVELS", "public,OUO,restricted")
        access_levels = [a.strip() for a in access_env.split(",") if a.strip()]

        return cls(
            primary_client=os.environ.get("PLATFORM_PRIMARY_CLIENT", "ddh"),
            valid_input_containers=valid_containers,
            valid_access_levels=access_levels,
            default_access_level=os.environ.get("PLATFORM_DEFAULT_ACCESS_LEVEL", "OUO"),
            vector_table_pattern=os.environ.get(
                "PLATFORM_VECTOR_TABLE_PATTERN",
                "{dataset_id}_{resource_id}_{version_id}"
            ),
            raster_output_folder_pattern=os.environ.get(
                "PLATFORM_RASTER_OUTPUT_PATTERN",
                "{dataset_id}/{resource_id}/{version_id}"
            ),
            stac_collection_pattern=os.environ.get(
                "PLATFORM_STAC_COLLECTION_PATTERN",
                "{dataset_id}"
            ),
            stac_item_pattern=os.environ.get(
                "PLATFORM_STAC_ITEM_PATTERN",
                "{dataset_id}_{resource_id}_{version_id}"
            ),
            request_id_length=int(os.environ.get("PLATFORM_REQUEST_ID_LENGTH", "32")),
            webhook_enabled=os.environ.get("PLATFORM_WEBHOOK_ENABLED", "false").lower() == "true",
            webhook_retry_count=int(os.environ.get("PLATFORM_WEBHOOK_RETRY_COUNT", "3")),
            webhook_retry_delay_seconds=int(os.environ.get("PLATFORM_WEBHOOK_RETRY_DELAY", "5"))
        )

    # ========================================================================
    # Helper Methods
    # ========================================================================

    def generate_vector_table_name(
        self,
        dataset_id: str,
        resource_id: str,
        version_id: str
    ) -> str:
        """
        Generate PostGIS table name from DDH identifiers.

        Args:
            dataset_id: DDH dataset identifier
            resource_id: DDH resource identifier
            version_id: DDH version identifier

        Returns:
            URL-safe, lowercase table name suitable for PostgreSQL

        Example:
            >>> config.generate_vector_table_name("Aerial-Imagery", "Site Alpha", "v1.0")
            'aerial_imagery_site_alpha_v1_0'
        """
        name = self.vector_table_pattern.format(
            dataset_id=dataset_id,
            resource_id=resource_id,
            version_id=version_id
        )
        return _slugify_for_postgres(name)

    def generate_raster_output_folder(
        self,
        dataset_id: str,
        resource_id: str,
        version_id: str
    ) -> str:
        """
        Generate COG output folder path from DDH identifiers.

        Args:
            dataset_id: DDH dataset identifier
            resource_id: DDH resource identifier
            version_id: DDH version identifier

        Returns:
            Path-safe folder structure for Azure Blob Storage

        Example:
            >>> config.generate_raster_output_folder("Aerial-Imagery", "Site Alpha", "v1.0")
            'aerial-imagery/site-alpha/v1.0'
        """
        path = self.raster_output_folder_pattern.format(
            dataset_id=dataset_id,
            resource_id=resource_id,
            version_id=version_id
        )
        return _slugify_for_path(path)

    def generate_stac_collection_id(
        self,
        dataset_id: str,
        resource_id: str = "",
        version_id: str = ""
    ) -> str:
        """
        Generate STAC collection ID from DDH identifiers.

        Args:
            dataset_id: DDH dataset identifier
            resource_id: DDH resource identifier (optional based on pattern)
            version_id: DDH version identifier (optional based on pattern)

        Returns:
            URL-safe STAC collection ID
        """
        collection_id = self.stac_collection_pattern.format(
            dataset_id=dataset_id,
            resource_id=resource_id,
            version_id=version_id
        )
        return _slugify_for_stac(collection_id)

    def generate_stac_item_id(
        self,
        dataset_id: str,
        resource_id: str,
        version_id: str
    ) -> str:
        """
        Generate STAC item ID from DDH identifiers.

        Args:
            dataset_id: DDH dataset identifier
            resource_id: DDH resource identifier
            version_id: DDH version identifier

        Returns:
            URL-safe STAC item ID
        """
        item_id = self.stac_item_pattern.format(
            dataset_id=dataset_id,
            resource_id=resource_id,
            version_id=version_id
        )
        return _slugify_for_stac(item_id)

    def is_valid_container(self, container_name: str) -> bool:
        """Check if container is in the allowed list."""
        return container_name in self.valid_input_containers

    def is_valid_access_level(self, access_level: str) -> bool:
        """Check if access level is valid."""
        return access_level in self.valid_access_levels

    def debug_dict(self) -> dict:
        """Return sanitized config for debugging."""
        return {
            'primary_client': self.primary_client,
            'valid_input_containers': self.valid_input_containers,
            'valid_access_levels': self.valid_access_levels,
            'vector_table_pattern': self.vector_table_pattern,
            'raster_output_folder_pattern': self.raster_output_folder_pattern,
            'stac_collection_pattern': self.stac_collection_pattern,
            'stac_item_pattern': self.stac_item_pattern,
            'webhook_enabled': self.webhook_enabled,
        }


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def generate_platform_request_id(
    dataset_id: str,
    resource_id: str,
    version_id: str,
    length: int = 32
) -> str:
    """
    Generate deterministic, idempotent Platform request ID from DDH identifiers.

    This function creates a unique, reproducible ID by hashing the three DDH
    identifiers. The same inputs will always produce the same output, enabling
    natural deduplication of Platform requests.

    Args:
        dataset_id: DDH dataset identifier
        resource_id: DDH resource identifier
        version_id: DDH version identifier
        length: Length of returned hash prefix (default 32, max 64)

    Returns:
        Hex string of SHA256 hash prefix (lowercase, URL-safe)

    Example:
        >>> generate_platform_request_id("aerial-2024", "site-alpha", "v1.0")
        'a3f2c1b8e9d7f6a5c4b3a2e1d9c8b7a6'

        >>> # Same inputs = same output (idempotent)
        >>> generate_platform_request_id("aerial-2024", "site-alpha", "v1.0")
        'a3f2c1b8e9d7f6a5c4b3a2e1d9c8b7a6'

    Note:
        This ID is used for:
        - Platform request tracking (api_requests table)
        - DDH status polling endpoint
        - Deduplication of resubmitted requests
    """
    # Combine identifiers with separator to avoid collisions
    # e.g., "a|bc|d" vs "ab|c|d" would produce different hashes
    combined = f"{dataset_id}|{resource_id}|{version_id}"

    # SHA256 hash (64 hex chars), truncate to requested length
    hash_hex = hashlib.sha256(combined.encode('utf-8')).hexdigest()

    return hash_hex[:min(length, 64)]


def _slugify_for_postgres(text: str) -> str:
    """
    Convert text to PostgreSQL-safe table/column name.

    Rules:
    - Lowercase
    - Replace spaces and hyphens with underscores
    - Remove non-alphanumeric characters (except underscores)
    - Collapse multiple underscores
    - Max 63 characters (PostgreSQL identifier limit)
    """
    slug = text.lower()
    slug = slug.replace(' ', '_').replace('-', '_')
    slug = re.sub(r'[^a-z0-9_]', '', slug)
    slug = re.sub(r'_+', '_', slug)
    slug = slug.strip('_')
    return slug[:63]


def _slugify_for_path(text: str) -> str:
    """
    Convert text to path-safe blob storage path.

    Rules:
    - Lowercase
    - Replace spaces with hyphens
    - Preserve forward slashes (path separators)
    - Remove other non-alphanumeric characters (except hyphens, underscores, dots)
    """
    slug = text.lower()
    slug = slug.replace(' ', '-')
    # Remove chars that aren't alphanumeric, hyphen, underscore, dot, or slash
    slug = re.sub(r'[^a-z0-9\-_./]', '', slug)
    # Collapse multiple slashes or hyphens
    slug = re.sub(r'-+', '-', slug)
    slug = re.sub(r'/+', '/', slug)
    return slug.strip('-/')


def _slugify_for_stac(text: str) -> str:
    """
    Convert text to STAC-compliant ID.

    STAC IDs should be:
    - URL-safe
    - Lowercase
    - Use hyphens as separators
    - Alphanumeric with hyphens and underscores
    """
    slug = text.lower()
    slug = slug.replace(' ', '-').replace('_', '-')
    slug = re.sub(r'[^a-z0-9\-]', '', slug)
    slug = re.sub(r'-+', '-', slug)
    return slug.strip('-')
