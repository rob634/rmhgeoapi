# ============================================================================
# CLAUDE CONTEXT - INFRASTRUCTURE
# ============================================================================
# PURPOSE: STAC (SpatioTemporal Asset Catalog) infrastructure for PgSTAC setup and management
# EXPORTS: StacInfrastructure class with schema detection, installation, and verification
# INTERFACES: None - concrete infrastructure class
# PYDANTIC_MODELS: None - uses dict responses for status
# DEPENDENCIES: pypgstac (0.8.5), psycopg, typing, subprocess
# SOURCE: PostgreSQL database connection from config, environment variables for pypgstac
# SCOPE: One-time PgSTAC installation, idempotent schema checks, version management
# VALIDATION: Schema existence checks, version verification, role validation
# PATTERNS: Infrastructure pattern, idempotent operations
# ENTRY_POINTS: StacInfrastructure().check_installation(), install_pgstac()
# INDEX: StacInfrastructure:50, check_installation:90, install_pgstac:150, verify_installation:250
# ============================================================================

"""
STAC Infrastructure Management

Handles PgSTAC installation, schema detection, and configuration.
PgSTAC controls its own schema naming and structure - this module
provides safe, idempotent installation and verification.

Key Design Principles:
- PgSTAC owns the 'pgstac' schema (cannot be changed)
- Installation is idempotent (safe to run multiple times)
- Separate from app schema (app.jobs, app.tasks)
- Production-safe: preserves data, only updates functions

Author: Robert and Geospatial Claude Legion
Date: 4 OCT 2025
"""

from typing import Dict, Any, Optional, List
import subprocess
import sys
import os
import json
import psycopg
from psycopg import sql

from util_logger import LoggerFactory, ComponentType
from config import get_config

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "StacInfrastructure")


class StacInfrastructure:
    """
    PgSTAC infrastructure management.

    Provides idempotent installation and verification of PgSTAC schema.
    All schema naming is controlled by PgSTAC library - we just trigger
    installation and verify results.

    Schema Structure (Fixed by PgSTAC):
    - Schema: pgstac (hardcoded, cannot change)
    - Roles: pgstac_admin, pgstac_ingest, pgstac_read
    - Tables: collections, items, partitions, etc.
    """

    # PgSTAC schema constants (controlled by library)
    PGSTAC_SCHEMA = "pgstac"
    PGSTAC_ROLES = ["pgstac_admin", "pgstac_ingest", "pgstac_read"]

    # =========================================================================
    # PRODUCTION COLLECTION STRATEGY
    # =========================================================================
    # CRITICAL: Bronze container is DEV/TEST ONLY - NOT in production STAC
    #
    # Production STAC Collections (3 types):
    # 1. "cogs"       - Cloud-optimized GeoTIFFs in EPSG:4326
    # 2. "vectors"    - PostGIS tables (queryable features)
    # 3. "geoparquet" - GeoParquet analytical datasets (future)
    #
    # Development: Use "dev" collection for testing with Bronze container
    # =========================================================================

    PRODUCTION_COLLECTIONS = {
        'cogs': {
            'title': 'Cloud-Optimized GeoTIFFs',
            'description': 'Raster data converted to COG format in EPSG:4326 for cloud-native access',
            'asset_type': 'raster',
            'media_type': 'image/tiff; application=geotiff; profile=cloud-optimized'
        },
        'vectors': {
            'title': 'Vector Features (PostGIS)',
            'description': 'Vector data stored in PostGIS tables, queryable via OGC API - Features',
            'asset_type': 'vector',
            'media_type': 'application/geo+json'
        },
        'geoparquet': {
            'title': 'GeoParquet Analytical Datasets',
            'description': 'Cloud-optimized columnar vector data for analytical queries',
            'asset_type': 'vector',
            'media_type': 'application/x-parquet'
        },
        'dev': {
            'title': 'Development & Testing',
            'description': 'Generic collection for development and testing (not for production)',
            'asset_type': 'mixed',
            'media_type': 'application/octet-stream'
        }
    }

    # Legacy tier constants (deprecated - kept for backward compatibility during migration)
    VALID_TIERS = ['bronze', 'silver', 'gold']

    TIER_DESCRIPTIONS = {
        'bronze': 'Raw geospatial data from Azure Storage container',
        'silver': 'Cloud-optimized GeoTIFFs (COGs) with validated metadata and PostGIS integration',
        'gold': 'GeoParquet exports optimized for analytical queries'
    }

    def __init__(self, connection_string: Optional[str] = None):
        """
        Initialize STAC infrastructure manager.

        Args:
            connection_string: PostgreSQL connection string (uses config if not provided)
        """
        self.config = get_config()
        # Use the SAME connection string as core machine (single source of truth)
        self.connection_string = connection_string or self.config.postgis_connection_string

    # =========================================================================
    # SCHEMA DETECTION - Fast idempotent checks
    # =========================================================================

    def check_installation(self) -> Dict[str, Any]:
        """
        Check if PgSTAC is installed (fast, idempotent).

        This is a lightweight check suitable for startup validation.
        Does NOT install anything - just checks existence.

        Returns:
            Dict with installation status:
            {
                'installed': bool,
                'schema_exists': bool,
                'version': str or None,
                'tables_count': int,
                'roles': List[str],
                'needs_migration': bool
            }
        """
        logger.info("🔍 Checking PgSTAC installation status...")

        try:
            with psycopg.connect(self.connection_string) as conn:
                with conn.cursor() as cur:
                    # Check schema existence
                    cur.execute(
                        sql.SQL("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname = %s)"),
                        [self.PGSTAC_SCHEMA]
                    )
                    schema_exists = cur.fetchone()[0]

                    if not schema_exists:
                        logger.info("❌ PgSTAC schema not found")
                        return {
                            'installed': False,
                            'schema_exists': False,
                            'version': None,
                            'tables_count': 0,
                            'roles': [],
                            'needs_migration': True
                        }

                    # Get version
                    version = None
                    try:
                        cur.execute("SELECT pgstac.get_version()")
                        version = cur.fetchone()[0]
                    except psycopg.Error:
                        logger.warning("⚠️ pgstac.get_version() failed - may need migration")

                    # Count tables in pgstac schema
                    cur.execute(
                        sql.SQL(
                            "SELECT COUNT(*) FROM information_schema.tables "
                            "WHERE table_schema = %s"
                        ),
                        [self.PGSTAC_SCHEMA]
                    )
                    tables_count = cur.fetchone()[0]

                    # Check roles
                    cur.execute(
                        "SELECT rolname FROM pg_roles WHERE rolname LIKE 'pgstac_%'"
                    )
                    roles = [row[0] for row in cur.fetchall()]

                    installed = (
                        schema_exists and
                        version is not None and
                        tables_count > 0 and
                        len(roles) >= 3
                    )

                    result = {
                        'installed': installed,
                        'schema_exists': schema_exists,
                        'version': version,
                        'tables_count': tables_count,
                        'roles': roles,
                        'needs_migration': not installed
                    }

                    if installed:
                        logger.info(f"✅ PgSTAC {version} installed ({tables_count} tables)")
                    else:
                        logger.warning(f"⚠️ PgSTAC schema exists but incomplete")

                    return result

        except (psycopg.Error, OSError) as e:
            logger.error(f"❌ Failed to check PgSTAC installation: {e}")
            logger.error(f"   Connection string: {self.connection_string}")
            logger.error(f"   Error type: {type(e).__name__}")
            return {
                'installed': False,
                'schema_exists': False,
                'version': None,
                'tables_count': 0,
                'roles': [],
                'needs_migration': True,
                'error': str(e)
            }

    # =========================================================================
    # INSTALLATION - One-time setup (idempotent)
    # =========================================================================

    def install_pgstac(self,
                       drop_existing: bool = False,
                       run_migrations: bool = True) -> Dict[str, Any]:
        """
        Install PgSTAC schema using pypgstac migrate.

        This uses the pypgstac CLI to run migrations. The pypgstac library
        controls all schema naming and structure - we just provide the
        database connection and trigger the process.

        Args:
            drop_existing: If True, drop pgstac schema before install (DESTRUCTIVE!)
            run_migrations: If True, run pypgstac migrate (default: True)

        Returns:
            Dict with installation results
        """
        logger.info("🚀 Starting PgSTAC installation...")

        # Safety check
        if drop_existing:
            logger.warning("⚠️ drop_existing=True - THIS WILL DELETE ALL STAC DATA!")
            if not self._confirm_drop():
                return {
                    'success': False,
                    'error': 'Installation cancelled - drop_existing requires confirmation'
                }

        try:
            # Drop existing schema if requested
            if drop_existing:
                self._drop_pgstac_schema()

            # Run pypgstac migrate
            if run_migrations:
                migration_result = self._run_pypgstac_migrate()
                if not migration_result['success']:
                    return migration_result

            # Verify installation
            verification = self.verify_installation()

            return {
                'success': verification['valid'],
                'version': verification.get('version'),
                'schema': self.PGSTAC_SCHEMA,
                'tables_created': verification.get('tables_count', 0),
                'roles_created': verification.get('roles', []),
                'migration_output': migration_result.get('output') if run_migrations else None,
                'verification': verification
            }

        except Exception as e:
            logger.error(f"❌ PgSTAC installation failed: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def _drop_pgstac_schema(self):
        """Drop pgstac schema (DESTRUCTIVE - development only!)."""
        logger.warning("💣 Dropping pgstac schema...")

        with psycopg.connect(self.connection_string) as conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(self.PGSTAC_SCHEMA)
                ))
                conn.commit()
                logger.info("✅ pgstac schema dropped")

    def _run_pypgstac_migrate(self) -> Dict[str, Any]:
        """
        Run pypgstac migrate using subprocess.

        Returns:
            Dict with migration results
        """
        logger.info("📦 Running pypgstac migrate...")

        try:
            # Set environment variables for pypgstac
            env = os.environ.copy()
            env.update({
                'PGHOST': self.config.postgis_host,
                'PGPORT': str(self.config.postgis_port),
                'PGDATABASE': self.config.postgis_database,
                'PGUSER': self.config.postgis_user,
                'PGPASSWORD': self.config.postgis_password
            })

            # Run pypgstac migrate
            # Use python -m with pypgstac.pypgstac for Azure Functions compatibility
            result = subprocess.run(
                [sys.executable, '-m', 'pypgstac.pypgstac', 'migrate'],
                env=env,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )

            if result.returncode == 0:
                logger.info("✅ pypgstac migrate completed successfully")
                return {
                    'success': True,
                    'output': result.stdout,
                    'returncode': result.returncode
                }
            else:
                logger.error(f"❌ pypgstac migrate failed: {result.stderr}")
                return {
                    'success': False,
                    'error': result.stderr,
                    'output': result.stdout,
                    'returncode': result.returncode
                }

        except subprocess.TimeoutExpired:
            logger.error("❌ pypgstac migrate timed out after 5 minutes")
            return {
                'success': False,
                'error': 'Migration timed out after 5 minutes'
            }
        except FileNotFoundError as e:
            logger.error(f"❌ pypgstac command not found: {e}")
            logger.error(f"   sys.executable: {sys.executable}")
            logger.error(f"   PATH: {os.environ.get('PATH', 'not set')}")
            return {
                'success': False,
                'error': f'pypgstac not found - {e}'
            }
        except Exception as e:
            logger.error(f"❌ pypgstac migrate error: {e}")
            logger.error(f"   Error type: {type(e).__name__}")
            import traceback
            logger.error(f"   Traceback: {traceback.format_exc()}")
            return {
                'success': False,
                'error': str(e)
            }

    def _confirm_drop(self) -> bool:
        """
        Confirm destructive drop operation.

        In production, this should always return False.
        For development, you can override this or use environment variable.

        Returns:
            True if drop confirmed, False otherwise
        """
        # Check for explicit confirmation environment variable
        confirm = os.getenv('PGSTAC_CONFIRM_DROP', 'false').lower()
        return confirm in ('true', '1', 'yes')

    # =========================================================================
    # VERIFICATION - Post-installation checks
    # =========================================================================

    def verify_installation(self) -> Dict[str, Any]:
        """
        Verify PgSTAC installation is complete and functional.

        Runs comprehensive checks:
        - Schema exists
        - Version query works
        - Tables exist
        - Roles configured
        - Search function available

        Returns:
            Dict with verification results
        """
        logger.info("🔍 Verifying PgSTAC installation...")

        checks = {
            'schema_exists': False,
            'version_query': False,
            'tables_exist': False,
            'roles_configured': False,
            'search_available': False,
            'version': None,
            'tables_count': 0,
            'roles': [],
            'errors': []
        }

        try:
            with psycopg.connect(self.connection_string) as conn:
                with conn.cursor() as cur:
                    # 1. Schema exists
                    cur.execute(
                        sql.SQL("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname = %s)"),
                        [self.PGSTAC_SCHEMA]
                    )
                    checks['schema_exists'] = cur.fetchone()[0]

                    if not checks['schema_exists']:
                        checks['errors'].append("pgstac schema does not exist")
                        checks['valid'] = False
                        return checks

                    # 2. Version query
                    try:
                        cur.execute("SELECT pgstac.get_version()")
                        checks['version'] = cur.fetchone()[0]
                        checks['version_query'] = True
                    except psycopg.Error as e:
                        checks['errors'].append(f"Version query failed: {e}")

                    # 3. Tables exist
                    cur.execute(
                        sql.SQL(
                            "SELECT COUNT(*) FROM information_schema.tables "
                            "WHERE table_schema = %s"
                        ),
                        [self.PGSTAC_SCHEMA]
                    )
                    checks['tables_count'] = cur.fetchone()[0]
                    checks['tables_exist'] = checks['tables_count'] > 0

                    if not checks['tables_exist']:
                        checks['errors'].append(f"No tables found in {self.PGSTAC_SCHEMA} schema")

                    # 4. Roles configured
                    cur.execute(
                        "SELECT rolname FROM pg_roles WHERE rolname LIKE 'pgstac_%'"
                    )
                    checks['roles'] = [row[0] for row in cur.fetchall()]
                    checks['roles_configured'] = len(checks['roles']) >= 3

                    if not checks['roles_configured']:
                        checks['errors'].append(f"Expected 3+ roles, found {len(checks['roles'])}")

                    # 5. Search function available
                    try:
                        # Test search with empty query (fast)
                        cur.execute("SELECT pgstac.search('{}') LIMIT 1")
                        checks['search_available'] = True
                    except psycopg.Error as e:
                        checks['errors'].append(f"Search function failed: {e}")

                    # Overall validation
                    checks['valid'] = (
                        checks['schema_exists'] and
                        checks['version_query'] and
                        checks['tables_exist'] and
                        checks['roles_configured'] and
                        checks['search_available']
                    )

                    if checks['valid']:
                        logger.info(f"✅ PgSTAC {checks['version']} verification passed")
                    else:
                        logger.warning(f"⚠️ PgSTAC verification failed: {checks['errors']}")

                    return checks

        except (psycopg.Error, OSError) as e:
            logger.error(f"❌ Verification error: {e}")
            logger.error(f"   Connection string: {self.connection_string}")
            logger.error(f"   Error type: {type(e).__name__}")
            checks['errors'].append(str(e))
            checks['valid'] = False
            return checks

    # =========================================================================
    # COLLECTION MANAGEMENT - Initial setup
    # =========================================================================

    def create_collection(self,
                         container: str,
                         tier: str,
                         collection_id: Optional[str] = None,
                         title: Optional[str] = None,
                         description: Optional[str] = None,
                         summaries: Optional[Dict[str, Any]] = None,
                         **kwargs) -> Dict[str, Any]:
        """
        Create STAC collection for any tier (Bronze/Silver/Gold).

        Args:
            container: Azure Storage container name (from config.bronze/silver/gold_container_name)
            tier: Collection tier ('bronze', 'silver', or 'gold')
            collection_id: Unique collection identifier (defaults to '{tier}-{container}')
            title: Human-readable title (defaults to generated title)
            description: Collection description (defaults to tier-appropriate description)
            summaries: Optional custom summaries to merge with defaults
            **kwargs: Additional STAC collection properties

        Returns:
            Dict with collection creation results

        Raises:
            ValueError: If tier is not in VALID_TIERS
        """
        # Validate tier
        tier = tier.lower()
        if tier not in self.VALID_TIERS:
            error_msg = f"Invalid tier '{tier}'. Must be one of: {', '.join(self.VALID_TIERS)}"
            logger.error(f"❌ {error_msg}")
            return {
                'success': False,
                'error': error_msg,
                'valid_tiers': self.VALID_TIERS
            }

        # Validate container
        if not container or not isinstance(container, str) or not container.strip():
            logger.error(f"❌ Invalid container name: {container}")
            return {
                'success': False,
                'error': 'Container must be a non-empty string',
                'provided': container
            }

        # Auto-generate IDs and titles if not provided
        collection_id = collection_id or f"{tier}-{container}"
        title = title or f"{tier.title()}: {container}"
        description = description or f"{self.TIER_DESCRIPTIONS[tier]} '{container}'"

        logger.info(f"📦 Creating {tier.upper()} collection: {collection_id} (container: {container})")

        # Build default summaries
        default_summaries = {
            "azure:container": [container],
            "azure:tier": [tier]
        }

        # Merge with custom summaries if provided
        final_summaries = {**default_summaries, **(summaries or {})}

        # Collection in STAC format
        collection = {
            "id": collection_id,
            "type": "Collection",
            "stac_version": "1.0.0",
            "title": title,
            "description": description,
            "license": "proprietary",
            "extent": {
                "spatial": {"bbox": [[-180, -90, 180, 90]]},
                "temporal": {"interval": [[None, None]]}
            },
            "summaries": final_summaries,
            **kwargs  # Allow additional STAC properties
        }

        try:
            with psycopg.connect(self.connection_string) as conn:
                with conn.cursor() as cur:
                    # Insert collection using pgstac function
                    cur.execute(
                        "SELECT * FROM pgstac.create_collection(%s)",
                        [json.dumps(collection)]
                    )
                    result = cur.fetchone()
                    conn.commit()

                    logger.info(f"✅ {tier.upper()} collection created: {collection_id}")
                    return {
                        'success': True,
                        'collection_id': collection_id,
                        'tier': tier,
                        'container': container,
                        'result': result
                    }

        except (psycopg.Error, OSError) as e:
            logger.error(f"❌ Failed to create {tier} collection: {e}")
            return {
                'success': False,
                'error': str(e),
                'error_type': type(e).__name__
            }

    def create_production_collection(self, collection_type: str) -> Dict[str, Any]:
        """
        Create one of the production STAC collections.

        Production collections:
        - "cogs": Cloud-optimized GeoTIFFs in EPSG:4326
        - "vectors": PostGIS tables (queryable features)
        - "geoparquet": GeoParquet analytical datasets
        - "dev": Development/testing (generic)

        Args:
            collection_type: One of PRODUCTION_COLLECTIONS keys

        Returns:
            Dict with collection creation results
        """
        if collection_type not in self.PRODUCTION_COLLECTIONS:
            error_msg = f"Invalid collection type '{collection_type}'. Must be one of: {', '.join(self.PRODUCTION_COLLECTIONS.keys())}"
            logger.error(f"❌ {error_msg}")
            return {
                'success': False,
                'error': error_msg,
                'valid_types': list(self.PRODUCTION_COLLECTIONS.keys())
            }

        coll_config = self.PRODUCTION_COLLECTIONS[collection_type]

        logger.info(f"📦 Creating production collection: {collection_type}")

        # Build STAC Collection
        collection = {
            "id": collection_type,
            "type": "Collection",
            "stac_version": "1.0.0",
            "title": coll_config['title'],
            "description": coll_config['description'],
            "license": "proprietary",
            "extent": {
                "spatial": {"bbox": [[-180, -90, 180, 90]]},
                "temporal": {"interval": [[None, None]]}
            },
            "summaries": {
                "asset_type": [coll_config['asset_type']],
                "media_type": [coll_config['media_type']]
            }
        }

        try:
            with psycopg.connect(self.connection_string) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT * FROM pgstac.create_collection(%s)",
                        [json.dumps(collection)]
                    )
                    result = cur.fetchone()
                    conn.commit()

                    logger.info(f"✅ Production collection created: {collection_type}")
                    return {
                        'success': True,
                        'collection_id': collection_type,
                        'collection_type': collection_type,
                        'config': coll_config,
                        'result': result
                    }

        except (psycopg.Error, OSError) as e:
            logger.error(f"❌ Failed to create collection '{collection_type}': {e}")
            return {
                'success': False,
                'error': str(e),
                'error_type': type(e).__name__
            }

    @staticmethod
    def determine_collection(asset_type: str, **kwargs) -> str:
        """
        Determine which production collection an asset belongs to.

        Args:
            asset_type: Type of asset ('raster', 'postgis_table', 'geoparquet', 'dev')
            **kwargs: Additional context (unused for now, reserved for future logic)

        Returns:
            Collection ID for this asset

        Examples:
            determine_collection('raster') → 'cogs'
            determine_collection('postgis_table') → 'vectors'
            determine_collection('geoparquet') → 'geoparquet'
            determine_collection('dev') → 'dev'
        """
        mapping = {
            'raster': 'cogs',
            'cog': 'cogs',
            'postgis_table': 'vectors',
            'vector': 'vectors',
            'geoparquet': 'geoparquet',
            'dev': 'dev',
            'test': 'dev'
        }

        return mapping.get(asset_type.lower(), 'dev')

    # =========================================================================
    # ITEM MANAGEMENT - Insert STAC Items into PgSTAC
    # =========================================================================

    def item_exists(self, item_id: str, collection_id: str) -> bool:
        """
        Check if STAC Item already exists in PgSTAC collection.

        Args:
            item_id: STAC Item ID to check
            collection_id: Collection to check in

        Returns:
            True if item exists, False otherwise
        """
        try:
            with psycopg.connect(self.connection_string) as conn:
                with conn.cursor() as cur:
                    # Query pgstac.items table for existing item
                    cur.execute(
                        "SELECT id FROM pgstac.items WHERE id = %s AND collection = %s",
                        (item_id, collection_id)
                    )
                    result = cur.fetchone()
                    exists = result is not None

                    if exists:
                        logger.debug(f"Item '{item_id}' already exists in collection '{collection_id}'")

                    return exists

        except (psycopg.Error, OSError) as e:
            logger.warning(f"Error checking if item exists: {e}")
            # On error, assume item doesn't exist (will fail on insert if it does)
            return False

    def insert_item(self, item, collection_id: str) -> Dict[str, Any]:
        """
        Insert STAC Item into PgSTAC.

        Args:
            item: stac-pydantic Item (already validated) or dict
            collection_id: Collection to insert item into

        Returns:
            Insertion result from PgSTAC

        Example:
            from stac_pydantic import Item
            item = Item(**item_dict)
            result = stac.insert_item(item, 'dev')
        """
        # Convert stac-pydantic Item to dict if needed
        if hasattr(item, 'model_dump'):
            item_dict = item.model_dump(mode='json', by_alias=True)
        else:
            item_dict = item

        item_id = item_dict.get('id', 'unknown')
        logger.info(f"Inserting STAC Item '{item_id}' into collection '{collection_id}'")

        try:
            with psycopg.connect(self.connection_string) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT * FROM pgstac.create_item(%s)",
                        [json.dumps(item_dict)]
                    )
                    result = cur.fetchone()
                    conn.commit()

                    logger.info(f"✅ STAC Item inserted: {item_id} → {collection_id}")
                    return {
                        'success': True,
                        'item_id': item_id,
                        'collection': collection_id,
                        'result': result
                    }

        except (psycopg.Error, OSError) as e:
            logger.error(f"❌ Failed to insert STAC Item '{item_id}': {e}")
            return {
                'success': False,
                'error': str(e),
                'error_type': type(e).__name__,
                'item_id': item_id,
                'collection': collection_id
            }

    def bulk_insert_items(self, items: list, collection_id: str) -> Dict[str, Any]:
        """
        Bulk insert STAC Items into PgSTAC.

        Args:
            items: List of stac-pydantic Items or dicts
            collection_id: Collection to insert items into

        Returns:
            Bulk insertion results with counts

        Example:
            items = [item1, item2, item3]
            result = stac.bulk_insert_items(items, 'cogs')
        """
        logger.info(f"Bulk inserting {len(items)} STAC Items into '{collection_id}'")

        inserted = []
        failed = []

        with psycopg.connect(self.connection_string) as conn:
            with conn.cursor() as cur:
                for item in items:
                    # Convert to dict if needed
                    if hasattr(item, 'model_dump'):
                        item_dict = item.model_dump(mode='json', by_alias=True)
                    else:
                        item_dict = item

                    item_id = item_dict.get('id', 'unknown')

                    try:
                        cur.execute(
                            "SELECT * FROM pgstac.create_item(%s)",
                            [json.dumps(item_dict)]
                        )
                        result = cur.fetchone()
                        inserted.append(item_id)
                        logger.debug(f"✅ Inserted: {item_id}")

                    except Exception as e:
                        failed.append({'item_id': item_id, 'error': str(e)})
                        logger.error(f"❌ Failed: {item_id} - {e}")

                conn.commit()

        logger.info(f"Bulk insert complete: {len(inserted)} succeeded, {len(failed)} failed")

        return {
            'success': len(failed) == 0,
            'inserted_count': len(inserted),
            'failed_count': len(failed),
            'inserted_items': inserted,
            'failed_items': failed,
            'collection': collection_id
        }


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def check_stac_installation() -> Dict[str, Any]:
    """
    Quick check if STAC is installed (for startup validation).

    Returns:
        Installation status dict
    """
    return StacInfrastructure().check_installation()


def install_stac(drop_existing: bool = False) -> Dict[str, Any]:
    """
    Install PgSTAC (for setup endpoints).

    Args:
        drop_existing: Drop schema before install (DESTRUCTIVE!)

    Returns:
        Installation results dict
    """
    return StacInfrastructure().install_pgstac(drop_existing=drop_existing)
