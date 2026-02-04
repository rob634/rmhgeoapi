"""
Configuration Package.

This package provides application configuration using a composition-based approach.

Structure:
    config/
    ├── __init__.py              # This file - exports and singleton
    ├── defaults.py              # Single source of truth for all default values
    ├── env_validation.py        # Regex-based env var validation (08 JAN 2026)
    ├── app_config.py            # Main config (composes domain configs)
    ├── app_mode_config.py       # Multi-Function App deployment modes
    ├── storage_config.py        # COG tiers, multi-account storage
    ├── database_config.py       # PostgreSQL/PostGIS
    ├── raster_config.py         # Raster pipeline settings
    ├── vector_config.py         # Vector pipeline settings
    ├── queue_config.py          # Service Bus queues
    ├── analytics_config.py      # DuckDB and columnar analytics
    ├── h3_config.py             # H3 hexagonal spatial indexing
    ├── platform_config.py       # DDH platform integration
    └── metrics_config.py        # Pipeline observability metrics

Usage:
    from config import get_config
    config = get_config()
    compression = config.raster.cog_compression

    # Import specific types
    from config import CogTier, QueueNames
    tier = CogTier.VISUALIZATION
    queue = QueueNames.JOBS

    # Get version
    from config import __version__
    print(f"Version: {__version__}")

    # Debug output
    from config import debug_config
    info = debug_config()  # Passwords masked

"""

# ============================================================================
# VERSION
# ============================================================================
# Semantic versioning follows MAJOR.MINOR.PATCH.BUILD
# Criteria for advance to 0.9.0: DAG refactor, full ETL separation, deprecate legacy fallbacks
__version__ = "0.8.9.2"

from typing import Optional

# Export defaults module (single source of truth for all default values)
from .defaults import (
    AzureDefaults,
    DatabaseDefaults,
    StorageDefaults,
    QueueDefaults,
    AppModeDefaults,
    TaskRoutingDefaults,
    RasterDefaults,
    VectorDefaults,
    AnalyticsDefaults,
    H3Defaults,
    PlatformDefaults,
    FathomDefaults,
    STACDefaults,
    ObservabilityDefaults,
    AppDefaults,
    KeyVaultDefaults,
)

# Export domain configs
from .storage_config import (
    CogTier,
    CogTierProfile,
    COG_TIER_PROFILES,
    StorageAccessTier,
    StorageAccountConfig,
    MultiAccountStorageConfig,
    StorageConfig,
    determine_applicable_tiers
)
from .database_config import DatabaseConfig, PublicDatabaseConfig, get_postgres_connection_string
from .raster_config import RasterConfig
from .vector_config import VectorConfig
from .queue_config import QueueConfig, QueueNames
from .analytics_config import AnalyticsConfig, DuckDBConnectionType
from .h3_config import H3Config
from .platform_config import PlatformConfig, generate_platform_request_id
from .metrics_config import MetricsConfig
from .observability_config import ObservabilityConfig
from .app_config import AppConfig
from .app_mode_config import AppMode, AppModeConfig, get_app_mode_config

# Environment variable validation (08 JAN 2026, updated 12 JAN 2026)
from .env_validation import (
    ENV_VAR_RULES,
    EnvVarRule,
    ValidationError as EnvValidationError,
    validate_environment,
    validate_single_var,
    get_validation_summary,
    log_validation_results,
)


# ============================================================================
# SINGLETON PATTERN
# ============================================================================

_config_instance: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """
    Get global configuration singleton - backward compatible.

    Returns:
        AppConfig instance loaded from environment

    Usage:
        config = get_config()
        host = config.database.host  # NEW pattern
        host = config.postgis_host   # OLD pattern (still works via legacy property)
    """
    global _config_instance
    if _config_instance is None:
        _config_instance = AppConfig.from_environment()
    return _config_instance


def debug_config() -> dict:
    """
    Get sanitized configuration for debugging (masks sensitive values).

    Returns:
        Dictionary with configuration values, passwords masked

    Usage:
        info = debug_config()
        print(info['database']['host'])  # Safe to log
        print(info['database']['password'])  # Shows "***MASKED***"
    """
    try:
        config = get_config()
        return {
            # Storage (zone-specific accounts - 31 DEC 2025)
            'storage': config.storage.debug_dict(),

            # Database
            'database': config.database.debug_dict(),
            'public_database': config.public_database.debug_dict() if config.public_database else None,
            'public_database_configured': config.is_public_database_configured(),

            # Raster (V0.8 - 24 JAN 2026)
            'raster': {
                'use_etl_mount': config.raster.use_etl_mount,
                'etl_mount_path': config.raster.etl_mount_path,
                'raster_tiling_threshold_mb': config.raster.raster_tiling_threshold_mb,
                'raster_tile_target_mb': config.raster.raster_tile_target_mb,
                'raster_collection_max_files': config.raster.raster_collection_max_files,
                'cog_compression': config.raster.cog_compression,
                'cog_tile_size': config.raster.cog_tile_size,
            },

            # Vector
            'vector': {
                'pickle_container': config.vector.pickle_container,
                'default_chunk_size': config.vector.default_chunk_size,
                'target_schema': config.vector.target_schema,
            },

            # Queues (11 DEC 2025 - No Legacy Fallbacks, 3 queues only)
            'queues': {
                'jobs_queue': config.queues.jobs_queue,
                'raster_tasks_queue': config.queues.raster_tasks_queue,
                'vector_tasks_queue': config.queues.vector_tasks_queue,
                'connection': '***MASKED***' if config.queues.connection_string else None,
            },

            # Analytics
            'analytics': config.analytics.debug_dict(),

            # H3
            'h3': config.h3.debug_dict(),

            # Platform
            'platform': config.platform.debug_dict(),

            # Metrics (E13: Pipeline Observability)
            'metrics': config.metrics.debug_dict(),

            # Application
            'observability': config.observability.debug_dict(),
            'debug_mode': config.debug_mode,  # Legacy alias
            'environment': config.environment,
            'function_timeout_minutes': config.function_timeout_minutes,
            'log_level': config.log_level,
        }
    except Exception as e:
        return {'error': f'Configuration validation failed: {e}'}


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Version
    '__version__',

    # Defaults (single source of truth)
    'AzureDefaults',
    'DatabaseDefaults',
    'StorageDefaults',
    'QueueDefaults',
    'AppModeDefaults',
    'TaskRoutingDefaults',
    'RasterDefaults',
    'VectorDefaults',
    'AnalyticsDefaults',
    'H3Defaults',
    'PlatformDefaults',
    'FathomDefaults',
    'STACDefaults',
    'ObservabilityDefaults',
    'AppDefaults',
    'KeyVaultDefaults',

    # Main config
    'AppConfig',
    'get_config',
    'debug_config',

    # App Mode (multi-Function App architecture)
    'AppMode',
    'AppModeConfig',
    'get_app_mode_config',

    # Storage
    'StorageConfig',
    'CogTier',
    'CogTierProfile',
    'COG_TIER_PROFILES',
    'StorageAccessTier',
    'StorageAccountConfig',
    'MultiAccountStorageConfig',
    'determine_applicable_tiers',

    # Database
    'DatabaseConfig',
    'PublicDatabaseConfig',
    'get_postgres_connection_string',

    # Raster
    'RasterConfig',

    # Vector
    'VectorConfig',

    # Queues
    'QueueConfig',
    'QueueNames',

    # Analytics
    'AnalyticsConfig',
    'DuckDBConnectionType',

    # H3
    'H3Config',

    # Platform
    'PlatformConfig',
    'generate_platform_request_id',

    # Metrics (E13: Pipeline Observability)
    'MetricsConfig',

    # Observability (F7.12.C: Flag Consolidation - 10 JAN 2026)
    'ObservabilityConfig',

    # Environment Variable Validation (08 JAN 2026, updated 12 JAN 2026)
    'ENV_VAR_RULES',
    'EnvVarRule',
    'EnvValidationError',
    'validate_environment',
    'validate_single_var',
    'get_validation_summary',
    'log_validation_results',
]
