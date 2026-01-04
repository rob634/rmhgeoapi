# ============================================================================
# SYSTEM SNAPSHOT SERVICE
# ============================================================================
# STATUS: Service - Configuration drift detection and system diagnostics
# PURPOSE: Capture, store, and compare system configuration snapshots
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: New file - part of system diagnostics enhancement
# ============================================================================
"""
System Snapshot Service.

Provides system configuration snapshot capture and drift detection for Azure
platform environments. Snapshots capture network configuration, instance info,
and config sources to detect changes in corporate environments where settings
may change without warning.

Trigger Points:
    - STARTUP: Cold start detection (once per instance)
    - SCHEDULED: Hourly timer for drift monitoring
    - MANUAL: On-demand via admin endpoint
    - DRIFT_DETECTED: Auto-captured when config hash changes

Exports:
    SnapshotService: Main service class (singleton)
    snapshot_service: Singleton instance

Dependencies:
    - config: Application configuration
    - infrastructure.postgresql: Database access
    - core.models.system_snapshot: Pydantic models
"""

import hashlib
import json
import os
import threading
import traceback
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from psycopg import sql

from config import get_config, __version__
from core.models import SystemSnapshotRecord, SnapshotTriggerType
from infrastructure.postgresql import PostgreSQLRepository
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "SnapshotService")


# ============================================================================
# SNAPSHOT REPOSITORY
# ============================================================================

class SnapshotRepository(PostgreSQLRepository):
    """
    Repository for system snapshot database operations.

    Handles CRUD operations for app.system_snapshots table.
    """

    def __init__(self):
        """Initialize with PostgreSQL connection."""
        super().__init__()
        self.table = "system_snapshots"
        self.schema = "app"

    def save(self, snapshot: SystemSnapshotRecord) -> SystemSnapshotRecord:
        """
        Save a system snapshot to the database.

        Args:
            snapshot: SystemSnapshotRecord to insert

        Returns:
            Created snapshot with snapshot_id populated
        """
        logger.info(f"Saving snapshot: trigger={snapshot.trigger_type.value}, hash={snapshot.config_hash[:16]}...")

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        INSERT INTO {}.{} (
                            captured_at, trigger_type, instance_id, role_instance_id,
                            config_hash, environment_type, sku, region,
                            vnet_private_ip, dns_server, vnet_route_all,
                            worker_process_count,
                            config_from_env_count, config_defaults_count, discovered_var_count,
                            full_snapshot,
                            has_drift, drift_details, previous_snapshot_id,
                            app_version, notes
                        ) VALUES (
                            %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s,
                            %s,
                            %s, %s, %s,
                            %s,
                            %s, %s, %s,
                            %s, %s
                        )
                        RETURNING snapshot_id
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (
                        snapshot.captured_at,
                        snapshot.trigger_type.value,
                        snapshot.instance_id,
                        snapshot.role_instance_id,
                        snapshot.config_hash,
                        snapshot.environment_type,
                        snapshot.sku,
                        snapshot.region,
                        snapshot.vnet_private_ip,
                        snapshot.dns_server,
                        snapshot.vnet_route_all,
                        snapshot.worker_process_count,
                        snapshot.config_from_env_count,
                        snapshot.config_defaults_count,
                        snapshot.discovered_var_count,
                        json.dumps(snapshot.full_snapshot),
                        snapshot.has_drift,
                        json.dumps(snapshot.drift_details) if snapshot.drift_details else None,
                        snapshot.previous_snapshot_id,
                        snapshot.app_version,
                        snapshot.notes
                    )
                )
                row = cur.fetchone()
                conn.commit()

                snapshot.snapshot_id = row[0]
                logger.info(f"Saved snapshot: id={snapshot.snapshot_id}")
                return snapshot

    def get_latest(self, instance_id: Optional[str] = None) -> Optional[SystemSnapshotRecord]:
        """
        Get the most recent snapshot.

        Args:
            instance_id: If provided, get latest for this instance only

        Returns:
            Most recent SystemSnapshotRecord or None
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                if instance_id:
                    cur.execute(
                        sql.SQL("""
                            SELECT * FROM {}.{}
                            WHERE instance_id = %s
                            ORDER BY captured_at DESC
                            LIMIT 1
                        """).format(
                            sql.Identifier(self.schema),
                            sql.Identifier(self.table)
                        ),
                        (instance_id,)
                    )
                else:
                    cur.execute(
                        sql.SQL("""
                            SELECT * FROM {}.{}
                            ORDER BY captured_at DESC
                            LIMIT 1
                        """).format(
                            sql.Identifier(self.schema),
                            sql.Identifier(self.table)
                        )
                    )
                row = cur.fetchone()
                return self._row_to_model(row) if row else None

    def get_by_id(self, snapshot_id: int) -> Optional[SystemSnapshotRecord]:
        """Get a snapshot by ID."""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("SELECT * FROM {}.{} WHERE snapshot_id = %s").format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (snapshot_id,)
                )
                row = cur.fetchone()
                return self._row_to_model(row) if row else None

    def list_with_drift(self, limit: int = 50) -> List[SystemSnapshotRecord]:
        """
        List snapshots where drift was detected.

        Args:
            limit: Maximum number of records to return

        Returns:
            List of snapshots with has_drift=True
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE has_drift = true
                        ORDER BY captured_at DESC
                        LIMIT %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (limit,)
                )
                rows = cur.fetchall()
                return [self._row_to_model(row) for row in rows]

    def list_recent(self, hours: int = 24, limit: int = 100) -> List[SystemSnapshotRecord]:
        """
        List recent snapshots.

        Args:
            hours: How many hours back to look
            limit: Maximum records to return

        Returns:
            List of recent SystemSnapshotRecords
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE captured_at > NOW() - INTERVAL '%s hours'
                        ORDER BY captured_at DESC
                        LIMIT %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (hours, limit)
                )
                rows = cur.fetchall()
                return [self._row_to_model(row) for row in rows]

    def _row_to_model(self, row) -> Optional[SystemSnapshotRecord]:
        """Convert database row to Pydantic model."""
        if not row:
            return None

        # Row is a tuple from psycopg cursor
        # Column order matches table definition
        return SystemSnapshotRecord(
            snapshot_id=row[0],
            captured_at=row[1],
            trigger_type=SnapshotTriggerType(row[2]),
            instance_id=row[3],
            role_instance_id=row[4],
            config_hash=row[5],
            environment_type=row[6],
            sku=row[7],
            region=row[8],
            vnet_private_ip=row[9],
            dns_server=row[10],
            vnet_route_all=row[11],
            worker_process_count=row[12],
            config_from_env_count=row[13],
            config_defaults_count=row[14],
            discovered_var_count=row[15],
            full_snapshot=row[16] if isinstance(row[16], dict) else json.loads(row[16]) if row[16] else {},
            has_drift=row[17],
            drift_details=row[18] if isinstance(row[18], dict) else json.loads(row[18]) if row[18] else None,
            previous_snapshot_id=row[19],
            app_version=row[20],
            notes=row[21]
        )


# ============================================================================
# SNAPSHOT SERVICE
# ============================================================================

class SnapshotService:
    """
    System configuration snapshot service.

    Captures system configuration snapshots and detects drift from previous
    configurations. Used for monitoring Azure platform changes in corporate
    environments.

    Singleton pattern for consistent state across invocations.
    """

    _instance: Optional['SnapshotService'] = None
    _lock = threading.Lock()

    def __new__(cls):
        """Singleton pattern with thread safety."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize service (only once due to singleton)."""
        if self._initialized:
            return

        logger.info("Initializing SnapshotService")
        self.config = get_config()
        self._repository: Optional[SnapshotRepository] = None
        self._initialized = True
        logger.info("SnapshotService initialized")

    @classmethod
    def instance(cls) -> 'SnapshotService':
        """Get singleton instance."""
        return cls()

    @property
    def repository(self) -> SnapshotRepository:
        """Lazy initialization of repository."""
        if self._repository is None:
            self._repository = SnapshotRepository()
        return self._repository

    # ========================================================================
    # CAPTURE METHODS
    # ========================================================================

    def capture_snapshot(
        self,
        trigger_type: SnapshotTriggerType,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Capture a system configuration snapshot.

        Gathers configuration data from multiple sources, computes a hash
        for drift detection, and saves to database.

        Args:
            trigger_type: What triggered this snapshot
            notes: Optional notes for manual snapshots

        Returns:
            Dict with snapshot summary and any drift detected
        """
        start_time = datetime.now(timezone.utc)
        logger.info(f"Capturing snapshot: trigger={trigger_type.value}")

        try:
            # Gather snapshot data
            snapshot_data = self._gather_snapshot_data()

            # Compute config hash
            config_hash = self._compute_config_hash(snapshot_data)

            # Get previous snapshot for drift detection
            previous = self.repository.get_latest()

            # Detect drift
            has_drift = False
            drift_details = None
            previous_snapshot_id = None

            if previous:
                previous_snapshot_id = previous.snapshot_id
                if previous.config_hash != config_hash:
                    has_drift = True
                    drift_details = self._compute_drift_details(
                        previous.full_snapshot,
                        snapshot_data
                    )
                    logger.warning(
                        f"Configuration drift detected! "
                        f"Previous hash: {previous.config_hash[:16]}..., "
                        f"Current hash: {config_hash[:16]}..."
                    )

            # Build record
            record = SystemSnapshotRecord(
                captured_at=start_time,
                trigger_type=trigger_type,
                instance_id=os.getenv('WEBSITE_INSTANCE_ID'),
                role_instance_id=os.getenv('WEBSITE_ROLE_INSTANCE_ID'),
                config_hash=config_hash,
                environment_type=snapshot_data.get('network', {}).get('summary', {}).get('environment_type'),
                sku=snapshot_data.get('platform', {}).get('sku'),
                region=snapshot_data.get('platform', {}).get('region'),
                vnet_private_ip=snapshot_data.get('network', {}).get('vnet', {}).get('private_ip'),
                dns_server=snapshot_data.get('network', {}).get('dns', {}).get('dns_server'),
                vnet_route_all=self._parse_bool(
                    snapshot_data.get('network', {}).get('vnet', {}).get('vnet_route_all')
                ),
                worker_process_count=self._parse_int(
                    snapshot_data.get('instance', {}).get('worker_config', {}).get('functions_worker_process_count')
                ),
                config_from_env_count=snapshot_data.get('config_sources', {}).get('summary', {}).get('from_environment', 0),
                config_defaults_count=snapshot_data.get('config_sources', {}).get('summary', {}).get('using_defaults', 0),
                discovered_var_count=snapshot_data.get('network', {}).get('summary', {}).get('total_vars_discovered', 0),
                full_snapshot=snapshot_data,
                has_drift=has_drift,
                drift_details=drift_details,
                previous_snapshot_id=previous_snapshot_id,
                app_version=__version__,
                notes=notes
            )

            # Save to database
            saved = self.repository.save(record)

            duration = (datetime.now(timezone.utc) - start_time).total_seconds()

            result = {
                "success": True,
                "snapshot_id": saved.snapshot_id,
                "trigger_type": trigger_type.value,
                "config_hash": config_hash[:16] + "...",
                "has_drift": has_drift,
                "duration_seconds": round(duration, 3),
                "captured_at": start_time.isoformat()
            }

            if has_drift:
                result["drift_summary"] = {
                    "previous_snapshot_id": previous_snapshot_id,
                    "changes_detected": len(drift_details.get('changes', [])) if drift_details else 0
                }
                # If drift detected and this wasn't already a drift trigger, log alert
                if trigger_type != SnapshotTriggerType.DRIFT_DETECTED:
                    logger.warning(f"DRIFT ALERT: Configuration changed! Snapshot ID: {saved.snapshot_id}")

            logger.info(
                f"Snapshot captured: id={saved.snapshot_id}, "
                f"drift={has_drift}, duration={duration:.3f}s"
            )

            return result

        except Exception as e:
            logger.error(f"Failed to capture snapshot: {e}")
            logger.error(traceback.format_exc())
            return {
                "success": False,
                "error": str(e),
                "trigger_type": trigger_type.value
            }

    def capture_startup_snapshot(self) -> Dict[str, Any]:
        """Capture snapshot during application startup."""
        return self.capture_snapshot(
            SnapshotTriggerType.STARTUP,
            notes="Cold start snapshot"
        )

    def capture_scheduled_snapshot(self) -> Dict[str, Any]:
        """Capture scheduled hourly snapshot."""
        return self.capture_snapshot(SnapshotTriggerType.SCHEDULED)

    def capture_manual_snapshot(self, notes: Optional[str] = None) -> Dict[str, Any]:
        """Capture manual snapshot from admin endpoint."""
        return self.capture_snapshot(
            SnapshotTriggerType.MANUAL,
            notes=notes or "Manual snapshot via admin endpoint"
        )

    # ========================================================================
    # DATA GATHERING
    # ========================================================================

    def _gather_snapshot_data(self) -> Dict[str, Any]:
        """
        Gather all data for the snapshot.

        Collects:
            - Network environment (VNet, DNS, ASE settings)
            - Instance information (worker config, process details)
            - Platform configuration (SKU, region)
            - Config sources (env vs defaults)

        Returns:
            Complete snapshot data dictionary
        """
        data = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "app_version": __version__
        }

        # Network environment (from health endpoint pattern)
        try:
            data["network"] = self._gather_network_environment()
        except Exception as e:
            logger.warning(f"Failed to gather network environment: {e}")
            data["network"] = {"error": str(e)}

        # Instance information
        try:
            data["instance"] = self._gather_instance_info()
        except Exception as e:
            logger.warning(f"Failed to gather instance info: {e}")
            data["instance"] = {"error": str(e)}

        # Platform configuration
        try:
            data["platform"] = self._gather_platform_config()
        except Exception as e:
            logger.warning(f"Failed to gather platform config: {e}")
            data["platform"] = {"error": str(e)}

        # Config sources
        try:
            data["config_sources"] = self._gather_config_sources()
        except Exception as e:
            logger.warning(f"Failed to gather config sources: {e}")
            data["config_sources"] = {"error": str(e)}

        return data

    def _gather_network_environment(self) -> Dict[str, Any]:
        """Gather network/VNet/ASE configuration from environment variables."""
        # VNet Integration Variables
        vnet_vars = {
            'private_ip': 'WEBSITE_PRIVATE_IP',
            'vnet_route_all': 'WEBSITE_VNET_ROUTE_ALL',
            'content_over_vnet': 'WEBSITE_CONTENTOVERVNET',
        }

        # DNS Configuration
        dns_vars = {
            'dns_server': 'WEBSITE_DNS_SERVER',
            'dns_alt_server': 'WEBSITE_DNS_ALT_SERVER',
        }

        # ASE (App Service Environment) specific
        ase_vars = {
            'ase_name': 'WEBSITE_SITE_NAME',
            'hosting_environment': 'WEBSITE_HOSTING_ENVIRONMENT_NAME',
            'internal_stamp_name': 'WEBSITE_INTERNAL_STAMP_NAME',
        }

        # Platform identification
        platform_vars = {
            'site_name': 'WEBSITE_SITE_NAME',
            'hostname': 'WEBSITE_HOSTNAME',
            'owner_name': 'WEBSITE_OWNER_NAME',
            'resource_group': 'WEBSITE_RESOURCE_GROUP',
            'slot_name': 'WEBSITE_SLOT_NAME',
            'sku': 'WEBSITE_SKU',
            'compute_mode': 'WEBSITE_COMPUTE_MODE',
            'region': 'REGION_NAME',
        }

        def get_category_values(var_dict):
            result = {}
            for key, env_var in var_dict.items():
                value = os.getenv(env_var)
                if value:
                    result[key] = value
            return result

        # Collect all categories
        vnet = get_category_values(vnet_vars)
        dns = get_category_values(dns_vars)
        ase = get_category_values(ase_vars)
        platform = get_category_values(platform_vars)

        # Discover unknown WEBSITE_*/AZURE_* variables
        known_prefixes = ['WEBSITE_', 'AZURE_', 'APPSETTING_']
        discovered = {}
        for key, value in os.environ.items():
            if any(key.startswith(prefix) for prefix in known_prefixes):
                # Don't include secrets
                if any(secret in key.lower() for secret in ['password', 'secret', 'key', 'token', 'credential']):
                    discovered[key] = "***MASKED***"
                else:
                    discovered[key] = value

        # Determine environment type
        if ase.get('hosting_environment'):
            env_type = "ase"
        elif vnet.get('private_ip'):
            env_type = "vnet_integrated"
        else:
            env_type = "standard"

        return {
            "vnet": vnet,
            "dns": dns,
            "ase": ase,
            "platform": platform,
            "discovered_vars": discovered,
            "summary": {
                "environment_type": env_type,
                "has_vnet": bool(vnet.get('private_ip')),
                "has_custom_dns": bool(dns.get('dns_server')),
                "is_ase": bool(ase.get('hosting_environment')),
                "total_vars_discovered": len(discovered)
            }
        }

    def _gather_instance_info(self) -> Dict[str, Any]:
        """Gather instance and worker configuration."""
        import multiprocessing

        return {
            "instance_id": os.getenv('WEBSITE_INSTANCE_ID'),
            "role_instance_id": os.getenv('WEBSITE_ROLE_INSTANCE_ID'),
            "worker_config": {
                "functions_worker_process_count": os.getenv('FUNCTIONS_WORKER_PROCESS_COUNT'),
                "functions_worker_runtime": os.getenv('FUNCTIONS_WORKER_RUNTIME'),
                "max_concurrent_requests_per_worker": os.getenv('FUNCTIONS_MAX_CONCURRENT_REQUESTS_PER_WORKER'),
            },
            "process": {
                "pid": os.getpid(),
                "cpu_count": multiprocessing.cpu_count(),
            },
            "python": {
                "version": os.getenv('PYTHON_VERSION') or os.getenv('FUNCTIONS_EXTENSION_VERSION'),
            }
        }

    def _gather_platform_config(self) -> Dict[str, Any]:
        """Gather Azure platform configuration."""
        return {
            "sku": os.getenv('WEBSITE_SKU'),
            "region": os.getenv('REGION_NAME'),
            "compute_mode": os.getenv('WEBSITE_COMPUTE_MODE'),
            "site_name": os.getenv('WEBSITE_SITE_NAME'),
            "resource_group": os.getenv('WEBSITE_RESOURCE_GROUP'),
            "owner_name": os.getenv('WEBSITE_OWNER_NAME'),
            "functions_extension_version": os.getenv('FUNCTIONS_EXTENSION_VERSION'),
        }

    def _gather_config_sources(self) -> Dict[str, Any]:
        """
        Gather configuration source information.

        Shows which configs came from environment vs defaults.
        """
        from config.defaults import (
            AzureDefaults, StorageDefaults, DatabaseDefaults
        )

        config = get_config()
        sources = {}

        # Key configurations to track
        checks = [
            ('bronze_storage_account', 'BRONZE_STORAGE_ACCOUNT',
             config.storage.bronze.account_name, StorageDefaults.DEFAULT_ACCOUNT_NAME),
            ('managed_identity_admin', 'DB_ADMIN_MANAGED_IDENTITY_NAME',
             config.database.managed_identity_admin_name, AzureDefaults.MANAGED_IDENTITY_NAME),
            ('postgis_host', 'POSTGIS_HOST', config.database.host, None),
            ('postgis_database', 'POSTGIS_DATABASE', config.database.database, None),
            ('titiler_base_url', 'TITILER_BASE_URL',
             config.titiler_base_url, AzureDefaults.TITILER_BASE_URL),
            ('etl_app_url', 'ETL_APP_URL',
             config.etl_app_base_url, AzureDefaults.ETL_APP_URL),
            ('service_bus_namespace', 'SERVICE_BUS_NAMESPACE',
             config.service_bus_namespace, None),
            ('debug_mode', 'DEBUG_MODE', config.debug_mode, False),
        ]

        for name, env_var, current_value, default_value in checks:
            env_val = os.getenv(env_var)
            sources[name] = {
                "source": "ENV" if env_val else "DEFAULT",
                "env_var": env_var,
                "is_default": not bool(env_val)
            }

        env_count = sum(1 for v in sources.values() if v['source'] == 'ENV')
        default_count = sum(1 for v in sources.values() if v['source'] == 'DEFAULT')

        return {
            "configs": sources,
            "summary": {
                "total_checked": len(sources),
                "from_environment": env_count,
                "using_defaults": default_count
            }
        }

    # ========================================================================
    # DRIFT DETECTION
    # ========================================================================

    def _compute_config_hash(self, snapshot_data: Dict[str, Any]) -> str:
        """
        Compute SHA256 hash of key configuration values.

        Only hashes stable configuration values (not timestamps, PIDs, etc.)
        to enable drift detection across snapshots.

        Args:
            snapshot_data: Full snapshot data

        Returns:
            64-character SHA256 hex digest
        """
        # Extract only stable config values for hashing
        hash_data = {
            "network_type": snapshot_data.get('network', {}).get('summary', {}).get('environment_type'),
            "vnet_private_ip": snapshot_data.get('network', {}).get('vnet', {}).get('private_ip'),
            "dns_server": snapshot_data.get('network', {}).get('dns', {}).get('dns_server'),
            "sku": snapshot_data.get('platform', {}).get('sku'),
            "region": snapshot_data.get('platform', {}).get('region'),
            "worker_process_count": snapshot_data.get('instance', {}).get('worker_config', {}).get('functions_worker_process_count'),
            "config_sources": snapshot_data.get('config_sources', {}).get('configs', {}),
        }

        # Create deterministic JSON string
        json_str = json.dumps(hash_data, sort_keys=True, default=str)

        return hashlib.sha256(json_str.encode()).hexdigest()

    def _compute_drift_details(
        self,
        previous: Dict[str, Any],
        current: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Compute detailed drift information between two snapshots.

        Args:
            previous: Previous snapshot's full_snapshot
            current: Current snapshot data

        Returns:
            Dictionary with change details
        """
        changes = []

        # Compare key fields
        comparisons = [
            ("environment_type",
             previous.get('network', {}).get('summary', {}).get('environment_type'),
             current.get('network', {}).get('summary', {}).get('environment_type')),
            ("vnet_private_ip",
             previous.get('network', {}).get('vnet', {}).get('private_ip'),
             current.get('network', {}).get('vnet', {}).get('private_ip')),
            ("dns_server",
             previous.get('network', {}).get('dns', {}).get('dns_server'),
             current.get('network', {}).get('dns', {}).get('dns_server')),
            ("sku",
             previous.get('platform', {}).get('sku'),
             current.get('platform', {}).get('sku')),
            ("region",
             previous.get('platform', {}).get('region'),
             current.get('platform', {}).get('region')),
            ("worker_process_count",
             previous.get('instance', {}).get('worker_config', {}).get('functions_worker_process_count'),
             current.get('instance', {}).get('worker_config', {}).get('functions_worker_process_count')),
        ]

        for field, old_val, new_val in comparisons:
            if old_val != new_val:
                changes.append({
                    "field": field,
                    "previous": old_val,
                    "current": new_val
                })

        # Compare config sources
        prev_sources = previous.get('config_sources', {}).get('configs', {})
        curr_sources = current.get('config_sources', {}).get('configs', {})

        for key in set(prev_sources.keys()) | set(curr_sources.keys()):
            prev_source = prev_sources.get(key, {}).get('source')
            curr_source = curr_sources.get(key, {}).get('source')
            if prev_source != curr_source:
                changes.append({
                    "field": f"config_source.{key}",
                    "previous": prev_source,
                    "current": curr_source
                })

        return {
            "changes": changes,
            "change_count": len(changes),
            "detected_at": datetime.now(timezone.utc).isoformat()
        }

    # ========================================================================
    # QUERY METHODS
    # ========================================================================

    def get_latest_snapshot(self) -> Optional[Dict[str, Any]]:
        """Get the most recent snapshot summary."""
        snapshot = self.repository.get_latest()
        if not snapshot:
            return None
        return {
            "snapshot_id": snapshot.snapshot_id,
            "captured_at": snapshot.captured_at.isoformat(),
            "trigger_type": snapshot.trigger_type.value,
            "config_hash": snapshot.config_hash[:16] + "...",
            "has_drift": snapshot.has_drift,
            "environment_type": snapshot.environment_type,
            "app_version": snapshot.app_version
        }

    def get_drift_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get snapshots where drift was detected."""
        snapshots = self.repository.list_with_drift(limit)
        return [
            {
                "snapshot_id": s.snapshot_id,
                "captured_at": s.captured_at.isoformat(),
                "trigger_type": s.trigger_type.value,
                "drift_details": s.drift_details,
                "previous_snapshot_id": s.previous_snapshot_id
            }
            for s in snapshots
        ]

    # ========================================================================
    # UTILITIES
    # ========================================================================

    def _parse_bool(self, value: Any) -> Optional[bool]:
        """Parse a value to boolean."""
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ('true', '1', 'yes')
        return bool(value)

    def _parse_int(self, value: Any) -> Optional[int]:
        """Parse a value to integer."""
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None


# Create singleton instance
snapshot_service = SnapshotService.instance()

__all__ = [
    'SnapshotService',
    'SnapshotRepository',
    'snapshot_service'
]
