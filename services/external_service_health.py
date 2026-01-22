# ============================================================================
# CLAUDE CONTEXT - EXTERNAL SERVICE HEALTH
# ============================================================================
# STATUS: Service - Health monitoring for external geospatial services
# PURPOSE: Perform health checks and send notifications for service outages
# CREATED: 22 JAN 2026
# LAST_REVIEWED: 22 JAN 2026
# ============================================================================
"""
External Service Health - Health Monitoring Service.

Performs health checks on external geospatial services and sends
notifications via Application Insights and Service Bus.

Key Features:
    - Service-type-specific health checks
    - Status transition management
    - Outage notifications (App Insights + Service Bus)
    - Recovery notifications

Notification Strategy:
    - First failure: App Insights WARNING
    - 3 consecutive failures: App Insights ERROR + Service Bus
    - Recovery: App Insights INFO + Service Bus

Exports:
    ExternalServiceHealthService: Health check orchestration
    HealthCheckResult: Check result dataclass
"""

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

from core.models.external_service import ExternalService, ServiceType, ServiceStatus
from infrastructure.external_service_repository import ExternalServiceRepository
from services.external_service_detector import ServiceDetector

# Logger setup
from util_logger import LoggerFactory, ComponentType
logger = LoggerFactory.create_logger(ComponentType.SERVICE, "service_health")


@dataclass
class HealthCheckResult:
    """Result of a single health check."""
    service_id: str
    success: bool
    response_ms: Optional[int]
    error: Optional[str]
    status_before: ServiceStatus
    status_after: ServiceStatus
    triggered_notification: bool


class ExternalServiceHealthService:
    """
    Health monitoring service for external geospatial services.

    Performs health checks, updates database state, and sends
    notifications for outages and recoveries.
    """

    # Thresholds
    DEGRADED_THRESHOLD_MS = 3000  # 3 seconds
    FAILURE_THRESHOLD = 3  # consecutive failures before outage

    def __init__(
        self,
        repository: Optional[ExternalServiceRepository] = None,
        detector: Optional[ServiceDetector] = None,
        service_bus_connection: Optional[str] = None
    ):
        """
        Initialize health service.

        Args:
            repository: Optional repository instance (creates one if not provided)
            detector: Optional detector instance
            service_bus_connection: Optional Service Bus connection string
        """
        self.repository = repository or ExternalServiceRepository()
        self.detector = detector or ServiceDetector()
        self._service_bus_connection = service_bus_connection

    def register_service(
        self,
        url: str,
        name: str,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        check_interval_minutes: int = 60
    ) -> ExternalService:
        """
        Register a new external service with automatic type detection.

        Args:
            url: Service endpoint URL
            name: Human-readable name
            description: Optional description
            tags: Optional list of tags
            check_interval_minutes: Health check interval

        Returns:
            Registered ExternalService
        """
        logger.info(f"Registering service: {name} ({url})")

        # Generate deterministic ID from URL
        service_id = ExternalService.generate_service_id(url)

        # Check if already registered
        existing = self.repository.get_by_id(service_id)
        if existing:
            logger.info(f"Service already registered: {service_id}")
            return existing

        # Detect service type
        detection = self.detector.detect(url)

        # Create service record
        service = ExternalService(
            service_id=service_id,
            url=url,
            name=name,
            description=description,
            tags=tags or [],
            service_type=detection.service_type,
            detection_confidence=detection.confidence,
            detected_capabilities=detection.capabilities,
            status=ServiceStatus.UNKNOWN,
            enabled=True,
            check_interval_minutes=check_interval_minutes,
            next_check_at=datetime.now(timezone.utc)  # Check immediately
        )

        created = self.repository.create(service)
        logger.info(f"Service registered: {service_id} as {detection.service_type.value} (confidence: {detection.confidence:.2f})")

        return created

    def check_service(self, service: ExternalService) -> HealthCheckResult:
        """
        Perform health check on a single service.

        Args:
            service: Service to check

        Returns:
            HealthCheckResult
        """
        logger.debug(f"Checking service: {service.name} ({service.service_type.value})")

        status_before = service.status
        start_time = time.time()

        # Perform service-type-specific health check
        success, error = self._perform_check(service)

        response_ms = int((time.time() - start_time) * 1000) if success else None

        # Determine new status
        if success:
            if response_ms and response_ms > self.DEGRADED_THRESHOLD_MS:
                # Check if degraded for multiple consecutive checks
                recent_slow = sum(
                    1 for h in service.health_history[-3:]
                    if h.get('success') and h.get('response_ms', 0) > self.DEGRADED_THRESHOLD_MS
                )
                if recent_slow >= 2:
                    new_status = ServiceStatus.DEGRADED
                else:
                    new_status = ServiceStatus.ACTIVE
            else:
                new_status = ServiceStatus.ACTIVE
        else:
            # Check consecutive failures
            if service.consecutive_failures + 1 >= self.FAILURE_THRESHOLD:
                new_status = ServiceStatus.OFFLINE
            else:
                new_status = status_before  # Keep previous status

        # Update database
        updated_service = self.repository.update_health_result(
            service_id=service.service_id,
            success=success,
            response_ms=response_ms,
            error=error,
            new_status=new_status
        )

        # Check if notification needed
        triggered_notification = False
        if status_before != new_status:
            self._send_status_change_notification(
                service,
                status_before,
                new_status,
                error
            )
            triggered_notification = True
        elif not success and service.consecutive_failures == 0:
            # First failure - warning only
            self._log_first_failure(service, error)

        return HealthCheckResult(
            service_id=service.service_id,
            success=success,
            response_ms=response_ms,
            error=error,
            status_before=status_before,
            status_after=new_status,
            triggered_notification=triggered_notification
        )

    def check_all_due(self, limit: int = 50) -> List[HealthCheckResult]:
        """
        Check all services due for health check.

        Args:
            limit: Maximum number of services to check

        Returns:
            List of HealthCheckResults
        """
        services = self.repository.get_services_due_for_check(limit=limit)
        logger.info(f"Found {len(services)} services due for health check")

        results = []
        for service in services:
            try:
                result = self.check_service(service)
                results.append(result)
            except Exception as e:
                logger.error(f"Error checking service {service.service_id}: {e}")
                results.append(HealthCheckResult(
                    service_id=service.service_id,
                    success=False,
                    response_ms=None,
                    error=str(e),
                    status_before=service.status,
                    status_after=service.status,
                    triggered_notification=False
                ))

        return results

    def _perform_check(self, service: ExternalService) -> tuple[bool, Optional[str]]:
        """
        Perform service-type-specific health check.

        Args:
            service: Service to check

        Returns:
            Tuple of (success, error_message)
        """
        if not HTTPX_AVAILABLE:
            return False, "httpx not available"

        try:
            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                # Service-type-specific checks
                if service.service_type in (
                    ServiceType.ARCGIS_MAPSERVER,
                    ServiceType.ARCGIS_FEATURESERVER,
                    ServiceType.ARCGIS_IMAGESERVER
                ):
                    return self._check_arcgis(client, service)

                elif service.service_type in (
                    ServiceType.WMS,
                    ServiceType.WFS,
                    ServiceType.WMTS
                ):
                    return self._check_ogc_legacy(client, service)

                elif service.service_type in (
                    ServiceType.OGC_API_FEATURES,
                    ServiceType.OGC_API_TILES
                ):
                    return self._check_ogc_api(client, service)

                elif service.service_type == ServiceType.STAC_API:
                    return self._check_stac(client, service)

                elif service.service_type in (ServiceType.XYZ_TILES, ServiceType.TMS_TILES):
                    return self._check_xyz(client, service)

                elif service.service_type == ServiceType.COG_ENDPOINT:
                    return self._check_cog(client, service)

                else:
                    # Generic check
                    return self._check_generic(client, service)

        except httpx.TimeoutException:
            return False, "Request timeout"
        except httpx.RequestError as e:
            return False, f"Request error: {str(e)}"
        except Exception as e:
            return False, f"Check error: {str(e)}"

    def _check_arcgis(self, client: httpx.Client, service: ExternalService) -> tuple[bool, Optional[str]]:
        """Check ArcGIS REST service."""
        response = client.get(service.url, params={'f': 'json'})
        if response.status_code == 200:
            try:
                data = response.json()
                # Verify it's a valid ArcGIS response
                if 'error' in data:
                    return False, f"ArcGIS error: {data['error'].get('message', 'Unknown')}"
                return True, None
            except Exception:
                return False, "Invalid JSON response"
        return False, f"HTTP {response.status_code}"

    def _check_ogc_legacy(self, client: httpx.Client, service: ExternalService) -> tuple[bool, Optional[str]]:
        """Check OGC legacy service (WMS/WFS/WMTS)."""
        service_name = service.service_type.value.upper()
        version = '1.3.0' if service_name == 'WMS' else '2.0.0' if service_name == 'WFS' else '1.0.0'

        response = client.get(service.url, params={
            'SERVICE': service_name,
            'REQUEST': 'GetCapabilities',
            'VERSION': version
        })

        if response.status_code == 200:
            # Check for valid XML
            if '<?xml' in response.text[:100] or '<' in response.text[:100]:
                return True, None
            return False, "Invalid XML response"
        return False, f"HTTP {response.status_code}"

    def _check_ogc_api(self, client: httpx.Client, service: ExternalService) -> tuple[bool, Optional[str]]:
        """Check OGC API service."""
        response = client.get(service.url, headers={'Accept': 'application/json'})
        if response.status_code == 200:
            try:
                data = response.json()
                if 'links' in data or 'collections' in data:
                    return True, None
                return True, None  # Accept any valid JSON
            except Exception:
                return False, "Invalid JSON response"
        return False, f"HTTP {response.status_code}"

    def _check_stac(self, client: httpx.Client, service: ExternalService) -> tuple[bool, Optional[str]]:
        """Check STAC API."""
        response = client.get(service.url, headers={'Accept': 'application/json'})
        if response.status_code == 200:
            try:
                data = response.json()
                if 'stac_version' in data:
                    return True, None
                return False, "Missing stac_version in response"
            except Exception:
                return False, "Invalid JSON response"
        return False, f"HTTP {response.status_code}"

    def _check_xyz(self, client: httpx.Client, service: ExternalService) -> tuple[bool, Optional[str]]:
        """Check XYZ/TMS tile service."""
        # Try tile 0/0/0
        import re
        test_url = service.url
        test_url = test_url.replace('{z}', '0').replace('{x}', '0').replace('{y}', '0')
        test_url = re.sub(r'\{[zxy]\}', '0', test_url, flags=re.IGNORECASE)

        response = client.get(test_url)
        if response.status_code == 200:
            content_type = response.headers.get('content-type', '')
            if 'image' in content_type:
                return True, None
            return False, f"Unexpected content type: {content_type}"
        return False, f"HTTP {response.status_code}"

    def _check_cog(self, client: httpx.Client, service: ExternalService) -> tuple[bool, Optional[str]]:
        """Check COG endpoint."""
        response = client.head(service.url)
        if response.status_code == 200:
            content_type = response.headers.get('content-type', '')
            if 'tiff' in content_type.lower():
                return True, None
            # Accept if URL ends in .tif
            if service.url.lower().endswith(('.tif', '.tiff')):
                return True, None
            return False, f"Unexpected content type: {content_type}"
        return False, f"HTTP {response.status_code}"

    def _check_generic(self, client: httpx.Client, service: ExternalService) -> tuple[bool, Optional[str]]:
        """Generic HTTP check."""
        response = client.get(service.url)
        if response.status_code == 200:
            return True, None
        return False, f"HTTP {response.status_code}"

    def _send_status_change_notification(
        self,
        service: ExternalService,
        status_before: ServiceStatus,
        status_after: ServiceStatus,
        error: Optional[str]
    ) -> None:
        """
        Send notification for status change.

        Logs to Application Insights and sends to Service Bus.

        Args:
            service: Service that changed
            status_before: Previous status
            status_after: New status
            error: Error message if failed
        """
        event_type = 'service_recovery' if status_after == ServiceStatus.ACTIVE else 'service_outage'

        # Build notification payload
        payload = {
            'event_type': event_type,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'service_id': service.service_id,
            'service_name': service.name,
            'service_type': service.service_type.value,
            'url': service.url,
            'previous_status': status_before.value,
            'new_status': status_after.value,
            'consecutive_failures': service.consecutive_failures,
            'last_failure_reason': error
        }

        # Log to Application Insights
        if status_after == ServiceStatus.OFFLINE:
            logger.error(
                f"SERVICE_OUTAGE: {service.name} ({service.service_type.value}) - "
                f"Status changed from {status_before.value} to {status_after.value}",
                extra={
                    'checkpoint': 'SERVICE_OUTAGE',
                    **payload
                }
            )
        elif status_after == ServiceStatus.ACTIVE and status_before != ServiceStatus.UNKNOWN:
            logger.info(
                f"SERVICE_RECOVERY: {service.name} ({service.service_type.value}) - "
                f"Status changed from {status_before.value} to {status_after.value}",
                extra={
                    'checkpoint': 'SERVICE_RECOVERY',
                    **payload
                }
            )
        elif status_after == ServiceStatus.DEGRADED:
            logger.warning(
                f"SERVICE_DEGRADED: {service.name} ({service.service_type.value}) - "
                f"Status changed from {status_before.value} to {status_after.value}",
                extra={
                    'checkpoint': 'SERVICE_DEGRADED',
                    **payload
                }
            )

        # Send to Service Bus if outage or recovery (not just degraded)
        if status_after in (ServiceStatus.OFFLINE, ServiceStatus.ACTIVE) and status_before != ServiceStatus.UNKNOWN:
            self._send_to_service_bus(payload)

    def _log_first_failure(self, service: ExternalService, error: Optional[str]) -> None:
        """Log first failure as warning (not yet an outage)."""
        logger.warning(
            f"SERVICE_FIRST_FAILURE: {service.name} ({service.service_type.value}) - {error}",
            extra={
                'checkpoint': 'SERVICE_FIRST_FAILURE',
                'service_id': service.service_id,
                'service_name': service.name,
                'service_type': service.service_type.value,
                'url': service.url,
                'error': error
            }
        )

    def _send_to_service_bus(self, payload: Dict[str, Any]) -> None:
        """
        Send notification to Service Bus queue.

        Args:
            payload: Notification payload
        """
        try:
            from azure.servicebus import ServiceBusClient, ServiceBusMessage
            from config import get_config

            config = get_config()
            connection_string = self._service_bus_connection or config.queues.connection_string

            if not connection_string:
                logger.warning("Service Bus connection not configured - skipping notification")
                return

            # Queue name for outage alerts
            queue_name = "service-outage-alerts"

            with ServiceBusClient.from_connection_string(connection_string) as client:
                with client.get_queue_sender(queue_name) as sender:
                    message = ServiceBusMessage(json.dumps(payload))
                    sender.send_messages(message)
                    logger.info(f"Sent {payload['event_type']} notification to Service Bus")

        except ImportError:
            logger.warning("azure-servicebus not available - skipping Service Bus notification")
        except Exception as e:
            logger.error(f"Failed to send Service Bus notification: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get service health statistics."""
        return self.repository.get_stats()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'ExternalServiceHealthService',
    'HealthCheckResult',
]
