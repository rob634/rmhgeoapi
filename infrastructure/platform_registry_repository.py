# ============================================================================
# PLATFORM REGISTRY REPOSITORY
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Infrastructure - CRUD operations for Platform registry
# PURPOSE: Database access for B2B platform configurations
# CREATED: 29 JAN 2026
# EXPORTS: PlatformRegistryRepository
# DEPENDENCIES: psycopg, core.models.platform_registry
# ============================================================================
"""
Platform Registry Repository.

CRUD operations for B2B platform configurations.
Platforms define what identifiers are required for asset lookup.

Example:
    repo = PlatformRegistryRepository()
    platform = repo.get("ddh")
    if platform:
        missing = platform.validate_refs({"dataset_id": "test"})
        # missing = ["resource_id", "version_id"]
"""

from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from psycopg import sql

from util_logger import LoggerFactory, ComponentType
from .postgresql import PostgreSQLRepository
from core.models.platform_registry import Platform

logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, "PlatformRegistryRepository")


class PlatformRegistryRepository(PostgreSQLRepository):
    """
    Repository for Platform registry CRUD operations.

    Platforms are B2B configurations that define:
    - Required identifier keys (e.g., dataset_id, resource_id, version_id)
    - Optional identifier keys
    - Whether the platform is active for new submissions

    Table: app.platforms
    """

    def __init__(self):
        """Initialize with app schema."""
        super().__init__()
        from config import get_config
        config = get_config()
        self.schema_name = config.database.app_schema

    # =========================================================================
    # READ OPERATIONS
    # =========================================================================

    def get(self, platform_id: str) -> Optional[Platform]:
        """
        Get a platform by ID.

        Args:
            platform_id: Platform identifier (e.g., "ddh")

        Returns:
            Platform if found, None otherwise
        """
        query = sql.SQL("""
            SELECT platform_id, display_name, description,
                   required_refs, optional_refs, is_active,
                   created_at, updated_at
            FROM {schema}.{table}
            WHERE platform_id = %s
        """).format(
            schema=sql.Identifier(self.schema_name),
            table=sql.Identifier("platforms")
        )

        result = self._execute_query(query, (platform_id,), fetch="one")
        if result:
            return self._row_to_platform(result)
        return None

    def get_active(self, platform_id: str) -> Optional[Platform]:
        """
        Get an active platform by ID.

        Args:
            platform_id: Platform identifier

        Returns:
            Platform if found and active, None otherwise
        """
        query = sql.SQL("""
            SELECT platform_id, display_name, description,
                   required_refs, optional_refs, is_active,
                   created_at, updated_at
            FROM {schema}.{table}
            WHERE platform_id = %s AND is_active = true
        """).format(
            schema=sql.Identifier(self.schema_name),
            table=sql.Identifier("platforms")
        )

        result = self._execute_query(query, (platform_id,), fetch="one")
        if result:
            return self._row_to_platform(result)
        return None

    def list_all(self, active_only: bool = True) -> List[Platform]:
        """
        List all platforms.

        Args:
            active_only: If True, only return active platforms

        Returns:
            List of Platform objects
        """
        if active_only:
            query = sql.SQL("""
                SELECT platform_id, display_name, description,
                       required_refs, optional_refs, is_active,
                       created_at, updated_at
                FROM {schema}.{table}
                WHERE is_active = true
                ORDER BY platform_id
            """).format(
                schema=sql.Identifier(self.schema_name),
                table=sql.Identifier("platforms")
            )
        else:
            query = sql.SQL("""
                SELECT platform_id, display_name, description,
                       required_refs, optional_refs, is_active,
                       created_at, updated_at
                FROM {schema}.{table}
                ORDER BY platform_id
            """).format(
                schema=sql.Identifier(self.schema_name),
                table=sql.Identifier("platforms")
            )

        results = self._execute_query(query, fetch="all")
        return [self._row_to_platform(row) for row in results]

    # =========================================================================
    # WRITE OPERATIONS
    # =========================================================================

    def create(self, platform: Platform) -> Platform:
        """
        Create a new platform.

        Args:
            platform: Platform to create

        Returns:
            Created Platform

        Raises:
            IntegrityError: If platform_id already exists
        """
        import json

        query = sql.SQL("""
            INSERT INTO {schema}.{table} (
                platform_id, display_name, description,
                required_refs, optional_refs, is_active,
                created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING platform_id
        """).format(
            schema=sql.Identifier(self.schema_name),
            table=sql.Identifier("platforms")
        )

        now = datetime.now(timezone.utc)
        params = (
            platform.platform_id,
            platform.display_name,
            platform.description,
            json.dumps(platform.required_refs),
            json.dumps(platform.optional_refs),
            platform.is_active,
            now,
            now
        )

        self._execute_query(query, params, fetch="one")
        logger.info(f"Created platform: {platform.platform_id}")

        return self.get(platform.platform_id)

    def update(self, platform_id: str, updates: Dict[str, Any]) -> Optional[Platform]:
        """
        Update a platform.

        Args:
            platform_id: Platform to update
            updates: Dictionary of fields to update

        Returns:
            Updated Platform if found, None otherwise
        """
        import json

        if not updates:
            return self.get(platform_id)

        # Build SET clause
        set_parts = []
        values = []
        for key, value in updates.items():
            if key in ('required_refs', 'optional_refs'):
                set_parts.append(sql.SQL("{} = %s").format(sql.Identifier(key)))
                values.append(json.dumps(value))
            else:
                set_parts.append(sql.SQL("{} = %s").format(sql.Identifier(key)))
                values.append(value)

        # Always update updated_at
        set_parts.append(sql.SQL("updated_at = %s"))
        values.append(datetime.now(timezone.utc))

        values.append(platform_id)

        query = sql.SQL("""
            UPDATE {schema}.{table}
            SET {sets}
            WHERE platform_id = %s
            RETURNING platform_id
        """).format(
            schema=sql.Identifier(self.schema_name),
            table=sql.Identifier("platforms"),
            sets=sql.SQL(", ").join(set_parts)
        )

        result = self._execute_query(query, tuple(values), fetch="one")
        if result:
            logger.info(f"Updated platform: {platform_id}")
            return self.get(platform_id)
        return None

    def deactivate(self, platform_id: str) -> bool:
        """
        Deactivate a platform (soft delete).

        Args:
            platform_id: Platform to deactivate

        Returns:
            True if deactivated, False if not found
        """
        query = sql.SQL("""
            UPDATE {schema}.{table}
            SET is_active = false, updated_at = %s
            WHERE platform_id = %s AND is_active = true
            RETURNING platform_id
        """).format(
            schema=sql.Identifier(self.schema_name),
            table=sql.Identifier("platforms")
        )

        result = self._execute_query(
            query,
            (datetime.now(timezone.utc), platform_id),
            fetch="one"
        )
        if result:
            logger.info(f"Deactivated platform: {platform_id}")
            return True
        return False

    # =========================================================================
    # VALIDATION
    # =========================================================================

    def validate_refs(self, platform_id: str, refs: Dict[str, Any]) -> List[str]:
        """
        Validate that refs contains all required keys for a platform.

        Args:
            platform_id: Platform to validate against
            refs: Dictionary of identifiers to validate

        Returns:
            List of missing required keys (empty if valid)

        Raises:
            ValueError: If platform not found
        """
        platform = self.get_active(platform_id)
        if not platform:
            raise ValueError(f"Platform not found or inactive: {platform_id}")

        return platform.validate_refs(refs)

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _row_to_platform(self, row: Dict[str, Any]) -> Platform:
        """Convert database row (dict) to Platform model."""
        return Platform(
            platform_id=row['platform_id'],
            display_name=row['display_name'],
            description=row.get('description'),
            required_refs=row.get('required_refs', []) if isinstance(row.get('required_refs'), list) else [],
            optional_refs=row.get('optional_refs', []) if isinstance(row.get('optional_refs'), list) else [],
            is_active=row.get('is_active', True),
            created_at=row.get('created_at'),
            updated_at=row.get('updated_at')
        )


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ['PlatformRegistryRepository']
