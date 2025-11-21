# ============================================================================
# CLAUDE CONTEXT - CONFIG PACKAGE INIT
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: New module - Phase 1 of config.py refactoring (20 NOV 2025)
# PURPOSE: Configuration package exports for backward compatibility
# LAST_REVIEWED: 20 NOV 2025
# EXPORTS: All config classes, get_config singleton, debug_config helper
# INTERFACES: Pydantic BaseModel
# PYDANTIC_MODELS: AppConfig, StorageConfig, DatabaseConfig, RasterConfig, VectorConfig, QueueConfig
# DEPENDENCIES: domain config modules
# SOURCE: Composed from domain configs
# SCOPE: Global configuration package
# VALIDATION: Pydantic v2 validation
# PATTERNS: Singleton, composition, facade
# ENTRY_POINTS: from config import get_config, CogTier, QueueNames
# INDEX: Exports:45, get_config:72, debug_config:85
# ============================================================================

"""
Configuration Package - Domain-Specific Configuration Modules

This package provides application configuration using a composition-based approach.

Structure:
    config/
    ├── __init__.py              # This file - exports and singleton
    ├── app_config.py            # Main config (composes domain configs)
    ├── storage_config.py        # COG tiers, multi-account storage
    ├── database_config.py       # PostgreSQL/PostGIS
    ├── raster_config.py         # Raster pipeline settings
    ├── vector_config.py         # Vector pipeline settings
    └── queue_config.py          # Service Bus queues

Usage:
    # Singleton pattern (preferred)
    from config import get_config
    config = get_config()
    compression = config.raster.cog_compression

    # Import specific types
    from config import CogTier, QueueNames
    tier = CogTier.VISUALIZATION
    queue = QueueNames.JOBS

    # Debug output
    from config import debug_config
    info = debug_config()  # Passwords masked

Created: 20 NOV 2025 as part of config.py god object refactoring
"""

from typing import Optional

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
from .database_config import DatabaseConfig, get_postgres_connection_string
from .raster_config import RasterConfig
from .vector_config import VectorConfig
from .queue_config import QueueConfig, QueueNames
from .analytics_config import AnalyticsConfig, DuckDBConnectionType
from .h3_config import H3Config
from .app_config import AppConfig


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
            # Storage
            'storage_account_name': config.storage_account_name,
            'storage': config.storage.debug_dict(),

            # Database
            'database': config.database.debug_dict(),

            # Raster
            'raster': {
                'cog_compression': config.raster.cog_compression,
                'cog_tile_size': config.raster.cog_tile_size,
                'size_threshold_mb': config.raster.size_threshold_mb,
            },

            # Vector
            'vector': {
                'pickle_container': config.vector.pickle_container,
                'default_chunk_size': config.vector.default_chunk_size,
                'target_schema': config.vector.target_schema,
            },

            # Queues
            'queues': {
                'jobs_queue': config.queues.jobs_queue,
                'tasks_queue': config.queues.tasks_queue,
                'connection': '***MASKED***' if config.queues.connection_string else None,
            },

            # Analytics
            'analytics': config.analytics.debug_dict(),

            # H3
            'h3': config.h3.debug_dict(),

            # Application
            'debug_mode': config.debug_mode,
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
    # Main config
    'AppConfig',
    'get_config',
    'debug_config',

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
]
