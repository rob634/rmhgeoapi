# ============================================================================
# CLAUDE CONTEXT - STAC INFRASTRUCTURE
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Infrastructure - PgSTAC setup and management
# PURPOSE: STAC (SpatioTemporal Asset Catalog) infrastructure for PgSTAC setup and management
# LAST_REVIEWED: 29 OCT 2025
# EXPORTS: StacInfrastructure class with schema detection, installation, and verification
# INTERFACES: None - concrete infrastructure class
# PYDANTIC_MODELS: None - uses dict responses for status
# DEPENDENCIES: pypgstac (0.8.5), psycopg, typing, subprocess, config
# SOURCE: PostgreSQL database connection from config, environment variables for pypgstac
# SCOPE: One-time PgSTAC installation, idempotent schema checks, version management
# VALIDATION: Schema existence checks, version verification, role validation
# PATTERNS: Infrastructure pattern, Idempotent operations
# ENTRY_POINTS: StacInfrastructure().check_installation(), install_pgstac(), verify_installation()
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

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "PgStacInfrastructure")


class PgStacInfrastructure:
    """
    PgSTAC Infrastructure Management (PostgreSQL STAC Extension).

    Handles PgSTAC (PostgreSQL STAC extension) installation, configuration, and operations.
    Provides idempotent installation and verification of PgSTAC schema.
    All schema naming is controlled by PgSTAC library - we just trigger
    installation and verify results.

    Schema Structure (Fixed by PgSTAC):
    - Schema: pgstac (hardcoded, cannot change)
    - Roles: pgstac_admin, pgstac_ingest, pgstac_read
    - Tables: collections, items, partitions, etc.

    Note: This class specifically manages PgSTAC (PostgreSQL extension), not generic STAC.
          For general STAC metadata generation, see services/service_stac_metadata.py

    Author: Robert and Geospatial Claude Legion
    Date: 5 OCT 2025 (Renamed to PgStacInfrastructure: 8 NOV 2025)
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
        # === SYSTEM STAC (Layer 1 - Operational Tracking) ===
        'system-vectors': {
            'title': 'System STAC - Vector Tables',
            'description': 'Operational tracking of PostGIS vector tables created by ETL',
            'asset_type': 'vector',
            'media_type': 'application/geo+json'
        },
        'system-rasters': {
            'title': 'System STAC - Raster Files',
            'description': 'Operational tracking of COG files created by ETL',
            'asset_type': 'raster',
            'media_type': 'image/tiff; application=geotiff; profile=cloud-optimized'
        },

        # === LEGACY COLLECTIONS (Pre-System STAC) ===
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
            container: Azure Storage container name (from config.storage.{zone}.get_container())
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
        Create one of the production STAC collections (idempotent).

        This method checks if the collection exists before attempting creation,
        making it safe to call multiple times (infrastructure-as-code pattern).

        Production collections:
        - "system-vectors": PostGIS vector tables created by ETL (System STAC Layer 1)
        - "system-rasters": COG raster files created by ETL (System STAC Layer 1)
        - "cogs": Cloud-optimized GeoTIFFs in EPSG:4326 (legacy)
        - "vectors": PostGIS tables (legacy)
        - "geoparquet": GeoParquet analytical datasets (legacy)
        - "dev": Development/testing (generic)

        Args:
            collection_type: One of PRODUCTION_COLLECTIONS keys

        Returns:
            Dict with collection creation results:
            {
                'success': bool,
                'existed': bool,  # True if collection already existed
                'collection_id': str,
                'collection_type': str,
                'config': dict,
                'result': Any  # PgSTAC function result (only if newly created)
            }

        Examples:
            >>> result = stac.create_production_collection('system-vectors')
            >>> result['success']  # True
            >>> result['existed']  # False (first run) or True (subsequent runs)
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
                    # Database-level idempotency check (18 OCT 2025)
                    # Check if collection already exists before attempting creation
                    logger.debug(f"🔍 Checking if collection '{collection_type}' exists...")
                    cur.execute(
                        "SELECT EXISTS(SELECT 1 FROM pgstac.collections WHERE id = %s)",
                        [collection_type]
                    )
                    exists = cur.fetchone()[0]

                    if exists:
                        logger.info(f"✅ Collection '{collection_type}' already exists (idempotent - skipping creation)")
                        return {
                            'success': True,
                            'existed': True,
                            'collection_id': collection_type,
                            'collection_type': collection_type,
                            'config': coll_config,
                            'message': 'Collection already exists (idempotent)'
                        }

                    # Create collection (only if doesn't exist)
                    logger.debug(f"📝 Creating new collection '{collection_type}'...")
                    cur.execute(
                        "SELECT * FROM pgstac.create_collection(%s)",
                        [json.dumps(collection)]
                    )
                    result = cur.fetchone()
                    conn.commit()

                    logger.info(f"✅ Production collection created: {collection_type}")
                    return {
                        'success': True,
                        'existed': False,
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


# ============================================================================
# STAC API QUERY METHODS (18 OCT 2025)
# ============================================================================
# STAC API standard endpoints for reading from pgstac schema
# These follow STAC API specification for interoperability
# ============================================================================

def get_all_collections() -> Dict[str, Any]:
    """
    Get all STAC collections (STAC API standard endpoint).

    Implements: GET /collections

    Returns STAC-compliant FeatureCollection of all collections.
    Uses pgstac.all_collections() function.

    Returns:
        Dict with 'collections' array and metadata
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "StacAPI")

    try:
        config = get_config()
        connection_string = config.postgis_connection_string

        with psycopg.connect(connection_string) as conn:
            with conn.cursor() as cur:
                # PgSTAC function to get all collections
                cur.execute("SELECT * FROM pgstac.all_collections()")
                result = cur.fetchone()

                if result and result[0]:
                    collections_data = result[0]

                    # STAC API standard response format
                    return {
                        'collections': collections_data if isinstance(collections_data, list) else [collections_data],
                        'links': [
                            {
                                'rel': 'self',
                                'type': 'application/json',
                                'href': '/collections'
                            }
                        ]
                    }
                else:
                    return {
                        'collections': [],
                        'links': [
                            {
                                'rel': 'self',
                                'type': 'application/json',
                                'href': '/collections'
                            }
                        ]
                    }

    except Exception as e:
        logger.error(f"Failed to get collections: {e}")
        return {
            'error': str(e),
            'error_type': type(e).__name__
        }


def get_collection(collection_id: str) -> Dict[str, Any]:
    """
    Get single STAC collection by ID (STAC API standard endpoint).

    Implements: GET /collections/{collection_id}

    Args:
        collection_id: Collection identifier

    Returns:
        STAC Collection object or error dict
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "StacAPI")

    try:
        config = get_config()
        connection_string = config.postgis_connection_string

        with psycopg.connect(connection_string) as conn:
            with conn.cursor() as cur:
                # PgSTAC function to get specific collection
                cur.execute(
                    "SELECT * FROM pgstac.get_collection(%s)",
                    [collection_id]
                )
                result = cur.fetchone()

                if result and result[0]:
                    return result[0]  # Return collection JSON
                else:
                    return {
                        'error': f"Collection '{collection_id}' not found",
                        'error_type': 'NotFound'
                    }

    except Exception as e:
        logger.error(f"Failed to get collection '{collection_id}': {e}")
        return {
            'error': str(e),
            'error_type': type(e).__name__
        }


def get_collection_items(
    collection_id: str,
    limit: int = 100,
    bbox: Optional[List[float]] = None,
    datetime_str: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get items in a collection (STAC API standard endpoint).

    Implements: GET /collections/{collection_id}/items

    Args:
        collection_id: Collection identifier
        limit: Maximum number of items to return (default 100)
        bbox: Bounding box filter [minx, miny, maxx, maxy]
        datetime_str: Datetime filter (RFC 3339 or interval)

    Returns:
        STAC ItemCollection (GeoJSON FeatureCollection)
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "StacAPI")

    try:
        config = get_config()
        connection_string = config.postgis_connection_string

        # Build search parameters (STAC search syntax)
        search_params = {
            'collections': [collection_id],
            'limit': limit
        }

        if bbox:
            search_params['bbox'] = bbox

        if datetime_str:
            search_params['datetime'] = datetime_str

        with psycopg.connect(connection_string) as conn:
            with conn.cursor() as cur:
                # Query items directly from pgstac.items table (simpler than search())
                # NOTE: pgstac.search() requires 'searches' table which may not be set up
                query = """
                    SELECT jsonb_build_object(
                        'type', 'FeatureCollection',
                        'features', COALESCE(jsonb_agg(content), '[]'::jsonb),
                        'links', '[]'::jsonb
                    )
                    FROM (
                        SELECT content
                        FROM pgstac.items
                        WHERE collection = %s
                        ORDER BY datetime DESC
                        LIMIT %s
                    ) items
                """
                cur.execute(query, [collection_id, limit])
                result = cur.fetchone()

                if result and result[0]:
                    return result[0]  # Returns GeoJSON FeatureCollection
                else:
                    # Empty FeatureCollection
                    return {
                        'type': 'FeatureCollection',
                        'features': [],
                        'links': []
                    }

    except Exception as e:
        logger.error(f"Failed to get items for collection '{collection_id}': {e}")
        return {
            'error': str(e),
            'error_type': type(e).__name__
        }


def search_items(
    collections: Optional[List[str]] = None,
    bbox: Optional[List[float]] = None,
    datetime_str: Optional[str] = None,
    limit: int = 100,
    query: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Search items across collections (STAC API standard endpoint).

    Implements: GET /search (also supports POST)

    Args:
        collections: List of collection IDs to search
        bbox: Bounding box [minx, miny, maxx, maxy]
        datetime_str: Datetime filter (RFC 3339 or interval)
        limit: Maximum items to return (default 100)
        query: Additional query parameters (STAC query extension)

    Returns:
        STAC ItemCollection (GeoJSON FeatureCollection)
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "StacAPI")

    try:
        config = get_config()
        connection_string = config.postgis_connection_string

        # Build search parameters
        search_params = {'limit': limit}

        if collections:
            search_params['collections'] = collections

        if bbox:
            search_params['bbox'] = bbox

        if datetime_str:
            search_params['datetime'] = datetime_str

        if query:
            search_params['query'] = query

        with psycopg.connect(connection_string) as conn:
            with conn.cursor() as cur:
                # Query items directly from pgstac.items table (simpler than search())
                # NOTE: pgstac.search() requires 'searches' table which may not be set up
                logger.debug(f"STAC search - collections: {collections}, limit: {limit}")

                # Build WHERE clause
                where_clauses = []
                params = []

                if collections:
                    where_clauses.append("collection = ANY(%s)")
                    params.append(collections)

                where_sql = " AND ".join(where_clauses) if where_clauses else "TRUE"

                query = f"""
                    SELECT jsonb_build_object(
                        'type', 'FeatureCollection',
                        'features', COALESCE(jsonb_agg(content), '[]'::jsonb),
                        'links', '[]'::jsonb
                    )
                    FROM (
                        SELECT content
                        FROM pgstac.items
                        WHERE {where_sql}
                        ORDER BY datetime DESC
                        LIMIT %s
                    ) items
                """
                params.append(limit)

                cur.execute(query, params)
                result = cur.fetchone()

                if result and result[0]:
                    return result[0]  # Returns GeoJSON FeatureCollection
                else:
                    # Empty FeatureCollection
                    return {
                        'type': 'FeatureCollection',
                        'features': [],
                        'links': []
                    }

    except Exception as e:
        logger.error(f"Failed to search items: {e}")
        return {
            'error': str(e),
            'error_type': type(e).__name__
        }


# =============================================================================
# STAC DATA CLEARING (DEV/TEST ONLY) - Added 29 OCT 2025
# =============================================================================

def clear_stac_data(mode: str = 'all') -> Dict[str, Any]:
    """
    Clear STAC data from pgstac tables (DEV/TEST ONLY).

    ⚠️ DESTRUCTIVE OPERATION - Deletes data but preserves schema structure.

    Args:
        mode: Clearing mode
              'items' - Delete only items (preserve collections)
              'collections' - Delete collections (CASCADE deletes items)
              'all' - Delete both collections and items (default)

    Returns:
        Dict with deletion results:
        {
            'success': True,
            'mode': 'all',
            'deleted': {
                'items': 1234,
                'collections': 5
            },
            'execution_time_ms': 456.78
        }

    Note:
        - Preserves pgstac schema structure
        - Preserves functions, indexes, partitions
        - Much faster than full schema drop/recreate
        - CASCADE automatically handles foreign key relationships

    Author: Robert and Geospatial Claude Legion
    Date: 29 OCT 2025
    """
    import time

    config = get_config()
    start_time = time.time()

    try:
        # Get counts before deletion
        with psycopg.connect(
            host=config.postgis_host,
            dbname=config.postgis_database,
            user=config.postgis_user,
            password=config.postgis_password,
            port=config.postgis_port
        ) as conn:
            with conn.cursor() as cur:
                # Get pre-deletion counts
                cur.execute("SELECT COUNT(*) FROM pgstac.items")
                items_before = cur.fetchone()[0]

                cur.execute("SELECT COUNT(*) FROM pgstac.collections")
                collections_before = cur.fetchone()[0]

                logger.info(f"🚨 STAC NUKE - Mode: {mode}")
                logger.info(f"   Items before: {items_before}")
                logger.info(f"   Collections before: {collections_before}")

                deleted = {'items': 0, 'collections': 0}

                if mode == 'items':
                    # Delete items only (preserve collections)
                    logger.warning("💣 Deleting all STAC items...")
                    cur.execute("DELETE FROM pgstac.items")
                    deleted['items'] = items_before
                    conn.commit()
                    logger.info(f"✅ Deleted {deleted['items']} items")

                elif mode == 'collections':
                    # Delete collections (CASCADE deletes items automatically)
                    logger.warning("💣 Deleting all STAC collections (CASCADE to items)...")
                    cur.execute("DELETE FROM pgstac.collections")
                    deleted['collections'] = collections_before
                    deleted['items'] = items_before  # CASCADE deleted
                    conn.commit()
                    logger.info(f"✅ Deleted {deleted['collections']} collections")
                    logger.info(f"✅ CASCADE deleted {deleted['items']} items")

                elif mode == 'all':
                    # Delete everything (collections CASCADE to items)
                    logger.warning("💣 Deleting all STAC collections and items...")
                    cur.execute("DELETE FROM pgstac.collections")
                    deleted['collections'] = collections_before
                    deleted['items'] = items_before  # CASCADE deleted
                    conn.commit()
                    logger.info(f"✅ Deleted {deleted['collections']} collections")
                    logger.info(f"✅ CASCADE deleted {deleted['items']} items")

                else:
                    return {
                        'success': False,
                        'error': f"Invalid mode: {mode}. Must be 'items', 'collections', or 'all'"
                    }

                execution_time_ms = (time.time() - start_time) * 1000

                return {
                    'success': True,
                    'mode': mode,
                    'deleted': deleted,
                    'counts_before': {
                        'items': items_before,
                        'collections': collections_before
                    },
                    'execution_time_ms': round(execution_time_ms, 2),
                    'warning': '⚠️ DEV/TEST ONLY - STAC data cleared (schema preserved)'
                }

    except Exception as e:
        logger.error(f"Failed to clear STAC data: {e}")
        return {
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__
        }


# ============================================================================
# PGSTAC SCHEMA INSPECTION (2 NOV 2025)
# ============================================================================
# Deep inspection endpoints for pgstac schema health and statistics
# ============================================================================

def get_schema_info() -> Dict[str, Any]:
    """
    Get detailed information about pgstac schema structure.

    Queries PostgreSQL system catalogs to inspect:
    - Tables and their sizes
    - Indexes
    - Functions
    - Partitions
    - Roles

    Returns:
        Dict with comprehensive schema information
    """
    from config import get_config

    config = get_config()
    connection_string = config.postgis_connection_string

    logger.info("🔍 Inspecting pgstac schema structure...")

    try:
        with psycopg.connect(connection_string) as conn:
            with conn.cursor() as cur:
                # Get PgSTAC version
                version = None
                try:
                    cur.execute("SELECT pgstac.get_version()")
                    version = cur.fetchone()[0]
                except psycopg.Error:
                    version = "unknown"

                # Get table information with sizes
                cur.execute("""
                    SELECT
                        t.tablename,
                        pg_total_relation_size(quote_ident(t.schemaname) || '.' || quote_ident(t.tablename)) / 1024.0 / 1024.0 as size_mb,
                        (SELECT COUNT(*) FROM information_schema.columns
                         WHERE table_schema = t.schemaname AND table_name = t.tablename) as column_count
                    FROM pg_tables t
                    WHERE t.schemaname = 'pgstac'
                    ORDER BY pg_total_relation_size(quote_ident(t.schemaname) || '.' || quote_ident(t.tablename)) DESC
                """)
                tables_raw = cur.fetchall()

                tables = {}
                for table_name, size_mb, col_count in tables_raw:
                    # Get row count for each table
                    try:
                        cur.execute(
                            sql.SQL("SELECT COUNT(*) FROM {}").format(
                                sql.Identifier('pgstac', table_name)
                            )
                        )
                        row_count = cur.fetchone()[0]
                    except psycopg.Error:
                        row_count = None

                    # Get indexes for this table
                    cur.execute("""
                        SELECT indexname
                        FROM pg_indexes
                        WHERE schemaname = 'pgstac' AND tablename = %s
                    """, [table_name])
                    indexes = [row[0] for row in cur.fetchall()]

                    tables[table_name] = {
                        'row_count': row_count,
                        'size_mb': round(size_mb, 2),
                        'column_count': col_count,
                        'indexes': indexes
                    }

                # Get functions
                cur.execute("""
                    SELECT routine_name
                    FROM information_schema.routines
                    WHERE routine_schema = 'pgstac'
                    ORDER BY routine_name
                """)
                functions = [row[0] for row in cur.fetchall()]

                # Get roles
                cur.execute(
                    "SELECT rolname FROM pg_roles WHERE rolname LIKE 'pgstac_%'"
                )
                roles = [row[0] for row in cur.fetchall()]

                # Get total schema size
                cur.execute("""
                    SELECT
                        pg_size_pretty(SUM(pg_total_relation_size(quote_ident(schemaname) || '.' || quote_ident(tablename)))) as total_size,
                        SUM(pg_total_relation_size(quote_ident(schemaname) || '.' || quote_ident(tablename))) / 1024.0 / 1024.0 as total_size_mb
                    FROM pg_tables
                    WHERE schemaname = 'pgstac'
                """)
                size_data = cur.fetchone()

                logger.info(f"✅ Schema inspection complete: {len(tables)} tables, {len(functions)} functions")

                return {
                    'schema': 'pgstac',
                    'version': version,
                    'total_size': size_data[0] if size_data else 'unknown',
                    'total_size_mb': round(size_data[1], 2) if size_data else 0,
                    'tables': tables,
                    'table_count': len(tables),
                    'function_count': len(functions),
                    'functions': functions[:20],  # First 20 functions
                    'roles': roles
                }

    except Exception as e:
        logger.error(f"❌ Schema inspection failed: {e}")
        return {
            'error': str(e),
            'error_type': type(e).__name__
        }


def get_collection_stats(collection_id: str) -> Dict[str, Any]:
    """
    Get detailed statistics for a specific STAC collection.

    Args:
        collection_id: Collection ID to analyze

    Returns:
        Dict with collection statistics including:
        - Item count
        - Total size
        - Spatial extent (actual bbox from items)
        - Temporal extent
        - Asset types and counts
        - Recent items
    """
    from config import get_config

    config = get_config()
    connection_string = config.postgis_connection_string

    logger.info(f"📊 Getting statistics for collection '{collection_id}'...")

    try:
        with psycopg.connect(connection_string) as conn:
            with conn.cursor() as cur:
                # Check if collection exists
                cur.execute(
                    "SELECT EXISTS(SELECT 1 FROM pgstac.collections WHERE id = %s)",
                    [collection_id]
                )
                if not cur.fetchone()[0]:
                    return {
                        'error': f"Collection '{collection_id}' not found",
                        'collection_id': collection_id
                    }

                # Get collection metadata
                cur.execute(
                    "SELECT content FROM pgstac.collections WHERE id = %s",
                    [collection_id]
                )
                collection_data = cur.fetchone()
                collection_json = collection_data[0] if collection_data else {}

                # Get item count
                cur.execute(
                    "SELECT COUNT(*) FROM pgstac.items WHERE collection = %s",
                    [collection_id]
                )
                item_count = cur.fetchone()[0]

                # Get spatial extent (actual bbox from items)
                cur.execute("""
                    SELECT
                        ST_XMin(ST_Extent(geometry)) as xmin,
                        ST_YMin(ST_Extent(geometry)) as ymin,
                        ST_XMax(ST_Extent(geometry)) as xmax,
                        ST_YMax(ST_Extent(geometry)) as ymax
                    FROM pgstac.items
                    WHERE collection = %s AND geometry IS NOT NULL
                """, [collection_id])
                bbox_data = cur.fetchone()
                actual_bbox = None
                if bbox_data and bbox_data[0] is not None:
                    actual_bbox = [float(x) for x in bbox_data]

                # Get temporal extent
                cur.execute("""
                    SELECT
                        MIN(datetime) as earliest,
                        MAX(datetime) as latest
                    FROM pgstac.items
                    WHERE collection = %s AND datetime IS NOT NULL
                """, [collection_id])
                temporal_data = cur.fetchone()

                # Get asset types
                cur.execute("""
                    SELECT
                        jsonb_object_keys(content->'assets') as asset_key,
                        COUNT(*) as count
                    FROM pgstac.items
                    WHERE collection = %s
                    GROUP BY asset_key
                """, [collection_id])
                assets = {row[0]: row[1] for row in cur.fetchall()}

                # Get recent items (last 5)
                cur.execute("""
                    SELECT id, content->>'datetime' as datetime
                    FROM pgstac.items
                    WHERE collection = %s
                    ORDER BY datetime DESC NULLS LAST
                    LIMIT 5
                """, [collection_id])
                recent_items = [
                    {'id': row[0], 'datetime': row[1]}
                    for row in cur.fetchall()
                ]

                logger.info(f"✅ Collection '{collection_id}' stats: {item_count} items")

                return {
                    'collection_id': collection_id,
                    'title': collection_json.get('title'),
                    'description': collection_json.get('description'),
                    'item_count': item_count,
                    'spatial_extent': {
                        'bbox': actual_bbox,
                        'configured_bbox': collection_json.get('extent', {}).get('spatial', {}).get('bbox', [[]])
                    },
                    'temporal_extent': {
                        'start': temporal_data[0].isoformat() if temporal_data and temporal_data[0] else None,
                        'end': temporal_data[1].isoformat() if temporal_data and temporal_data[1] else None,
                        'span_days': (temporal_data[1] - temporal_data[0]).days if temporal_data and temporal_data[0] and temporal_data[1] else None
                    },
                    'assets': assets,
                    'recent_items': recent_items,
                    'has_items': item_count > 0
                }

    except Exception as e:
        logger.error(f"❌ Failed to get collection stats for '{collection_id}': {e}")
        return {
            'error': str(e),
            'error_type': type(e).__name__,
            'collection_id': collection_id
        }


def get_item_by_id(item_id: str, collection_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Get a single STAC item by ID.

    Args:
        item_id: STAC item ID
        collection_id: Optional collection ID to narrow search

    Returns:
        STAC Item JSON or error dict
    """
    from config import get_config

    config = get_config()
    connection_string = config.postgis_connection_string

    logger.info(f"🔍 Looking up item '{item_id}'" + (f" in collection '{collection_id}'" if collection_id else ""))

    try:
        with psycopg.connect(connection_string) as conn:
            with conn.cursor() as cur:
                if collection_id:
                    # Search in specific collection
                    cur.execute(
                        "SELECT content FROM pgstac.items WHERE id = %s AND collection = %s",
                        [item_id, collection_id]
                    )
                else:
                    # Search across all collections
                    cur.execute(
                        "SELECT content FROM pgstac.items WHERE id = %s",
                        [item_id]
                    )

                result = cur.fetchone()

                if result:
                    logger.info(f"✅ Found item '{item_id}'")
                    return result[0]  # Return STAC Item JSON directly
                else:
                    logger.warning(f"⚠️ Item '{item_id}' not found")
                    return {
                        'error': f"Item '{item_id}' not found" + (f" in collection '{collection_id}'" if collection_id else ""),
                        'item_id': item_id,
                        'collection_id': collection_id
                    }

    except Exception as e:
        logger.error(f"❌ Failed to get item '{item_id}': {e}")
        return {
            'error': str(e),
            'error_type': type(e).__name__,
            'item_id': item_id
        }


def get_health_metrics() -> Dict[str, Any]:
    """
    Get overall pgstac health metrics.

    Returns:
        Dict with health status, counts, and performance indicators
    """
    from config import get_config

    config = get_config()
    connection_string = config.postgis_connection_string

    logger.info("🏥 Checking pgstac health...")

    try:
        with psycopg.connect(connection_string) as conn:
            with conn.cursor() as cur:
                # Check schema exists
                cur.execute(
                    "SELECT EXISTS(SELECT 1 FROM information_schema.schemata WHERE schema_name = 'pgstac')"
                )
                schema_exists = cur.fetchone()[0]

                if not schema_exists:
                    return {
                        'status': 'unhealthy',
                        'schema_exists': False,
                        'message': 'pgstac schema does not exist'
                    }

                # Get version
                try:
                    cur.execute("SELECT pgstac.get_version()")
                    version = cur.fetchone()[0]
                except psycopg.Error:
                    version = "unknown"

                # Get counts
                cur.execute("SELECT COUNT(*) FROM pgstac.collections")
                collections_count = cur.fetchone()[0]

                cur.execute("SELECT COUNT(*) FROM pgstac.items")
                items_count = cur.fetchone()[0]

                # Get database size
                cur.execute("""
                    SELECT
                        SUM(pg_total_relation_size(quote_ident(schemaname) || '.' || quote_ident(tablename))) / 1024.0 / 1024.0
                    FROM pg_tables
                    WHERE schemaname = 'pgstac'
                """)
                db_size_mb = round(cur.fetchone()[0], 2)

                # Check for issues
                issues = []
                if items_count == 0 and collections_count > 0:
                    issues.append("Collections exist but no items found")

                status = 'healthy' if schema_exists and not issues else 'warning'

                logger.info(f"✅ Health check complete: {status}")

                return {
                    'status': status,
                    'schema_exists': schema_exists,
                    'version': version,
                    'collections_count': collections_count,
                    'items_count': items_count,
                    'database_size_mb': db_size_mb,
                    'issues': issues,
                    'message': f"PgSTAC {version} - {collections_count} collections, {items_count} items"
                }

    except Exception as e:
        logger.error(f"❌ Health check failed: {e}")
        return {
            'status': 'error',
            'error': str(e),
            'error_type': type(e).__name__
        }


def get_collections_summary() -> Dict[str, Any]:
    """
    Get quick summary of all collections with key statistics.

    Returns:
        Dict with summary statistics for all collections
    """
    from config import get_config

    config = get_config()
    connection_string = config.postgis_connection_string

    logger.info("📋 Getting collections summary...")

    try:
        with psycopg.connect(connection_string) as conn:
            with conn.cursor() as cur:
                # Get all collections with item counts
                cur.execute("""
                    SELECT
                        c.id,
                        c.content->>'title' as title,
                        c.content->>'description' as description,
                        COUNT(i.id) as item_count,
                        MAX(i.datetime) as last_updated
                    FROM pgstac.collections c
                    LEFT JOIN pgstac.items i ON i.collection = c.id
                    GROUP BY c.id, c.content
                    ORDER BY c.id
                """)

                collections = []
                total_items = 0

                for row in cur.fetchall():
                    coll_id, title, description, item_count, last_updated = row
                    total_items += item_count

                    collections.append({
                        'id': coll_id,
                        'title': title,
                        'description': description[:100] + '...' if description and len(description) > 100 else description,
                        'item_count': item_count,
                        'last_updated': last_updated.isoformat() if last_updated else None
                    })

                logger.info(f"✅ Collections summary: {len(collections)} collections, {total_items} total items")

                return {
                    'total_collections': len(collections),
                    'total_items': total_items,
                    'collections': collections
                }

    except Exception as e:
        logger.error(f"❌ Failed to get collections summary: {e}")
        return {
            'error': str(e),
            'error_type': type(e).__name__
        }
