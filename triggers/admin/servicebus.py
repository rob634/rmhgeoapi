# ============================================================================
# SERVICE BUS ADMIN HTTP TRIGGER
# ============================================================================
# STATUS: Trigger layer - GET/POST /api/servicebus/*
# PURPOSE: Service Bus queue monitoring and management endpoints
# LAST_REVIEWED: 05 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: ServiceBusAdminTrigger, servicebus_admin_trigger
# DEPENDENCIES: azure.servicebus
# ============================================================================
"""
Service Bus Admin HTTP Trigger.

Service Bus queue monitoring and management endpoints.

Consolidated endpoint pattern (15 DEC 2025):
    GET /api/servicebus?type={queues|health}
    GET|POST /api/servicebus/queue/{queue_name}?type={details|peek|deadletter|nuke}

Exports:
    ServiceBusAdminTrigger: HTTP trigger class for Service Bus operations
    servicebus_admin_trigger: Singleton instance of ServiceBusAdminTrigger
"""

import azure.functions as func
import json
import os
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from azure.servicebus import ServiceBusClient, ServiceBusSubQueue
from azure.servicebus.management import ServiceBusAdministrationClient
from azure.servicebus.exceptions import ServiceBusError
from azure.identity import DefaultAzureCredential

from util_logger import LoggerFactory, ComponentType
from config import AppConfig
from config.defaults import QueueDefaults


@dataclass
class RouteDefinition:
    """Route configuration for registry pattern."""
    route: str
    methods: list
    handler: str
    description: str


class ServiceBusAdminTrigger:
    """
    Service Bus admin trigger for queue monitoring and management.

    Provides read-only inspection endpoints and a nuclear button for clearing queues.
    Follows patterns established in Phase 1 database admin implementation.

    Consolidated API (15 DEC 2025):
        GET /api/servicebus?type={queues|health}
        GET|POST /api/servicebus/queue/{queue_name}?type={details|peek|deadletter|nuke}
    """

    # ========================================================================
    # ROUTE REGISTRY - Single source of truth for function_app.py
    # ========================================================================
    ROUTES = [
        RouteDefinition(
            route="servicebus",
            methods=["GET"],
            handler="handle_global",
            description="Global ops: ?type={queues|health}"
        ),
        RouteDefinition(
            route="servicebus/queue/{queue_name}",
            methods=["GET", "POST"],
            handler="handle_queue",
            description="Queue ops: ?type={details|peek|deadletter|nuke}"
        ),
    ]

    # ========================================================================
    # OPERATIONS REGISTRIES - Maps type param to handler method
    # ========================================================================
    GLOBAL_OPERATIONS = {
        "queues": "_list_queues",
        "health": "_get_health",
    }

    QUEUE_OPERATIONS = {
        "details": "_get_queue_details",
        "peek": "_peek_messages",
        "deadletter": "_peek_deadletter",
        "nuke": "_nuke_queue",
    }

    def __init__(self):
        """Initialize Service Bus admin trigger with lazy-loaded clients."""
        self.logger = LoggerFactory.create_logger(
            ComponentType.TRIGGER,
            "ServiceBusAdmin"
        )

        # Lazy initialization - clients created on first use
        self._admin_client = None
        self._service_bus_client = None
        self._config = None

        # Known queue names from QueueDefaults (11 DEC 2025 - No Legacy Fallbacks)
        # Updated 11 JAN 2026: Added long-running-tasks queue for Docker worker
        self._known_queues = [
            QueueDefaults.JOBS_QUEUE,
            QueueDefaults.RASTER_TASKS_QUEUE,
            QueueDefaults.VECTOR_TASKS_QUEUE,
            QueueDefaults.LONG_RUNNING_TASKS_QUEUE,
        ]

        self.logger.info("🔧 Initializing ServiceBusAdminTrigger")
        self.logger.info("✅ ServiceBusAdminTrigger initialized")

    @property
    def config(self) -> AppConfig:
        """Lazy load configuration."""
        if self._config is None:
            from config import get_config
            self._config = get_config()
        return self._config

    @property
    def admin_client(self) -> ServiceBusAdministrationClient:
        """Lazy initialization of Service Bus administration client."""
        if self._admin_client is None:
            self.logger.debug("🔧 Lazy loading Service Bus admin client")

            # Priority 1: Connection string (local dev)
            conn_str = self.config.service_bus_connection_string

            if conn_str:
                self.logger.info("🔑 Using connection string for Service Bus admin")
                self._admin_client = ServiceBusAdministrationClient.from_connection_string(conn_str)
            else:
                # Priority 2: Managed Identity (production)
                namespace = self.config.service_bus_namespace
                if not namespace:
                    raise ValueError(
                        "SERVICE_BUS_NAMESPACE or ServiceBusConnection__fullyQualifiedNamespace required "
                        "for managed identity authentication"
                    )

                self.logger.info(f"🔐 Using DefaultAzureCredential for admin client: {namespace}")
                credential = DefaultAzureCredential()

                self._admin_client = ServiceBusAdministrationClient(
                    fully_qualified_namespace=namespace,
                    credential=credential
                )

            self.logger.debug("✅ Service Bus admin client loaded")

        return self._admin_client

    @property
    def service_bus_client(self) -> ServiceBusClient:
        """Lazy initialization of Service Bus client for message operations."""
        if self._service_bus_client is None:
            self.logger.debug("🔧 Lazy loading Service Bus client")

            # Priority 1: Connection string (local dev)
            conn_str = self.config.service_bus_connection_string

            if conn_str:
                self.logger.info("🔑 Using connection string for Service Bus client")
                self._service_bus_client = ServiceBusClient.from_connection_string(conn_str)
            else:
                # Priority 2: Managed Identity (production)
                namespace = self.config.service_bus_namespace
                if not namespace:
                    raise ValueError(
                        "SERVICE_BUS_NAMESPACE or ServiceBusConnection__fullyQualifiedNamespace required "
                        "for managed identity authentication"
                    )

                self.logger.info(f"🔐 Using DefaultAzureCredential for Service Bus client: {namespace}")
                credential = DefaultAzureCredential()

                self._service_bus_client = ServiceBusClient(
                    fully_qualified_namespace=namespace,
                    credential=credential
                )

            self.logger.debug("✅ Service Bus client loaded")

        return self._service_bus_client

    def handle_global(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Consolidated global Service Bus operations.

        GET /api/servicebus?type={queues|health}

        Query Parameters:
            type: Operation type (default: queues)
                - queues: List all queues with metrics
                - health: Service Bus health check

        Returns:
            JSON response with requested data
        """
        try:
            op_type = req.params.get('type', 'queues')
            self.logger.info(f"📥 Service Bus global request: type={op_type}")

            if op_type not in self.GLOBAL_OPERATIONS:
                return func.HttpResponse(
                    body=json.dumps({
                        'error': f"Unknown operation type: {op_type}",
                        'valid_types': list(self.GLOBAL_OPERATIONS.keys()),
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    }),
                    status_code=400,
                    mimetype='application/json'
                )

            handler_method = getattr(self, self.GLOBAL_OPERATIONS[op_type])
            return handler_method(req)

        except Exception as e:
            self.logger.error(f"❌ Error in handle_global: {e}")
            self.logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def handle_queue(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Consolidated queue-specific Service Bus operations.

        GET|POST /api/servicebus/queue/{queue_name}?type={details|peek|deadletter|nuke}

        Path Parameters:
            queue_name: Name of the Service Bus queue

        Query Parameters:
            type: Operation type (default: details)
                - details: Queue properties and metrics (GET)
                - peek: Preview active messages (GET)
                - deadletter: Preview dead letter messages (GET)
                - nuke: Clear queue messages (POST, requires confirm=yes)

        Returns:
            JSON response with requested data
        """
        try:
            queue_name = req.route_params.get('queue_name')
            if not queue_name:
                return func.HttpResponse(
                    body=json.dumps({'error': 'queue_name is required'}),
                    status_code=400,
                    mimetype='application/json'
                )

            op_type = req.params.get('type', 'details')
            self.logger.info(f"📥 Service Bus queue request: queue={queue_name}, type={op_type}")

            if op_type not in self.QUEUE_OPERATIONS:
                return func.HttpResponse(
                    body=json.dumps({
                        'error': f"Unknown operation type: {op_type}",
                        'valid_types': list(self.QUEUE_OPERATIONS.keys()),
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    }),
                    status_code=400,
                    mimetype='application/json'
                )

            # Check method for nuke operation
            if op_type == 'nuke' and req.method != 'POST':
                return func.HttpResponse(
                    body=json.dumps({
                        'error': 'nuke operation requires POST method',
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    }),
                    status_code=405,
                    mimetype='application/json'
                )

            handler_method = getattr(self, self.QUEUE_OPERATIONS[op_type])
            return handler_method(req, queue_name)

        except Exception as e:
            self.logger.error(f"❌ Error in handle_queue: {e}")
            self.logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def _list_queues(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        List all queues with metrics.

        GET /api/admin/servicebus/queues

        Returns:
            JSON with array of queues, each containing:
            - queue_name
            - active_messages
            - dead_letter_messages
            - scheduled_messages
            - total_messages
            - size_bytes
            - max_size_mb
            - utilization_percent
        """
        try:
            self.logger.info("📋 Listing all Service Bus queues")

            queues = []
            total_active = 0
            total_dead_letter = 0

            for queue_name in self._known_queues:
                try:
                    # Get both runtime properties and queue configuration
                    runtime_props = self.admin_client.get_queue_runtime_properties(queue_name)
                    queue_props = self.admin_client.get_queue(queue_name)

                    active = runtime_props.active_message_count
                    dead_letter = runtime_props.dead_letter_message_count
                    scheduled = runtime_props.scheduled_message_count
                    total = active + dead_letter + scheduled

                    size_bytes = runtime_props.size_in_bytes
                    max_size_bytes = queue_props.max_size_in_megabytes * 1024 * 1024
                    utilization_percent = (size_bytes / max_size_bytes * 100) if max_size_bytes > 0 else 0

                    queues.append({
                        'queue_name': queue_name,
                        'active_messages': active,
                        'dead_letter_messages': dead_letter,
                        'scheduled_messages': scheduled,
                        'total_messages': total,
                        'size_bytes': size_bytes,
                        'max_size_mb': queue_props.max_size_in_megabytes,
                        'utilization_percent': round(utilization_percent, 2)
                    })

                    total_active += active
                    total_dead_letter += dead_letter

                except Exception as e:
                    self.logger.warning(f"Could not get metrics for queue {queue_name}: {e}")
                    queues.append({
                        'queue_name': queue_name,
                        'error': str(e)
                    })

            self.logger.info(f"✅ Found {len(queues)} queues")

            return func.HttpResponse(
                body=json.dumps({
                    'queues': queues,
                    'total_queues': len(queues),
                    'total_active_messages': total_active,
                    'total_dead_letter_messages': total_dead_letter,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except ServiceBusError as e:
            self.logger.error(f"❌ Service Bus error: {e}")
            return func.HttpResponse(
                body=json.dumps({
                    'error': f'Service Bus error: {str(e)}',
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=503,
                mimetype='application/json'
            )

        except Exception as e:
            self.logger.error(f"❌ Error listing queues: {e}")
            self.logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def _get_queue_details(self, req: func.HttpRequest, queue_name: str) -> func.HttpResponse:
        """
        Get detailed queue metrics and properties.

        GET /api/admin/servicebus/queues/{queue_name}

        Args:
            queue_name: Name of the queue

        Returns:
            JSON with detailed queue information including properties and metrics
        """
        try:
            self.logger.info(f"📊 Getting details for queue: {queue_name}")

            # Validate queue name
            if queue_name not in self._known_queues:
                return func.HttpResponse(
                    body=json.dumps({
                        'error': f'Unknown queue: {queue_name}',
                        'known_queues': self._known_queues
                    }),
                    status_code=404,
                    mimetype='application/json'
                )

            # Get runtime properties
            runtime_props = self.admin_client.get_queue_runtime_properties(queue_name)

            # Get queue properties (configuration)
            queue_props = self.admin_client.get_queue(queue_name)

            result = {
                'queue_name': queue_name,
                'active_messages': runtime_props.active_message_count,
                'dead_letter_messages': runtime_props.dead_letter_message_count,
                'scheduled_messages': runtime_props.scheduled_message_count,
                'transfer_message_count': runtime_props.transfer_message_count,
                'transfer_dead_letter_message_count': runtime_props.transfer_dead_letter_message_count,
                'properties': {
                    'max_delivery_count': queue_props.max_delivery_count,
                    'lock_duration_seconds': queue_props.lock_duration.total_seconds(),
                    'default_message_ttl_seconds': queue_props.default_message_time_to_live.total_seconds() if queue_props.default_message_time_to_live else None,
                    'requires_session': queue_props.requires_session,
                    'requires_duplicate_detection': queue_props.requires_duplicate_detection,
                    'duplicate_detection_history_seconds': queue_props.duplicate_detection_history_time_window.total_seconds() if queue_props.duplicate_detection_history_time_window else None,
                    'enable_batched_operations': queue_props.enable_batched_operations,
                    'enable_partitioning': queue_props.enable_partitioning,
                    'max_size_in_megabytes': queue_props.max_size_in_megabytes,
                    'status': queue_props.status.value if hasattr(queue_props.status, 'value') else str(queue_props.status)
                },
                'size_bytes': runtime_props.size_in_bytes,
                'created_at': runtime_props.created_at_utc.isoformat() if runtime_props.created_at_utc else None,
                'updated_at': runtime_props.updated_at_utc.isoformat() if runtime_props.updated_at_utc else None,
                'accessed_at': runtime_props.accessed_at_utc.isoformat() if runtime_props.accessed_at_utc else None,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

            self.logger.info(f"✅ Retrieved details for queue {queue_name}")

            return func.HttpResponse(
                body=json.dumps(result, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except ServiceBusError as e:
            self.logger.error(f"❌ Service Bus error: {e}")
            return func.HttpResponse(
                body=json.dumps({
                    'error': f'Service Bus error: {str(e)}',
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=503,
                mimetype='application/json'
            )

        except Exception as e:
            self.logger.error(f"❌ Error getting queue details: {e}")
            self.logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def _peek_messages(self, req: func.HttpRequest, queue_name: str) -> func.HttpResponse:
        """
        Peek at active messages WITHOUT dequeuing (read-only).

        GET /api/admin/servicebus/queues/{queue_name}/peek?limit=10

        Query Params:
            limit: Max messages to peek (default: 10, max: 100)

        Args:
            queue_name: Name of the queue

        Returns:
            JSON with array of peeked messages (not removed from queue)
        """
        try:
            # Get limit parameter
            limit = int(req.params.get('limit', '10'))
            limit = min(limit, 100)  # Cap at 100

            self.logger.info(f"👀 Peeking {limit} messages from queue: {queue_name}")

            # Validate queue name
            if queue_name not in self._known_queues:
                return func.HttpResponse(
                    body=json.dumps({
                        'error': f'Unknown queue: {queue_name}',
                        'known_queues': self._known_queues
                    }),
                    status_code=404,
                    mimetype='application/json'
                )

            # Get queue metrics first
            runtime_props = self.admin_client.get_queue_runtime_properties(queue_name)
            total_in_queue = runtime_props.active_message_count

            # Peek messages
            messages = []
            with self.service_bus_client.get_queue_receiver(queue_name) as receiver:
                peeked = receiver.peek_messages(max_message_count=limit)

                for msg in peeked:
                    # Get message body
                    try:
                        body_str = str(msg)
                        # Truncate if too long
                        if len(body_str) > 500:
                            body_str = body_str[:500] + "..."
                    except Exception as e:
                        self.logger.debug(f"Could not parse message body: {e}")
                        body_str = "<unable to parse>"

                    messages.append({
                        'sequence_number': msg.sequence_number,
                        'message_id': msg.message_id,
                        'enqueued_time': msg.enqueued_time_utc.isoformat() if msg.enqueued_time_utc else None,
                        'delivery_count': msg.delivery_count,
                        'content_preview': body_str,
                        'content_type': msg.content_type,
                        'correlation_id': msg.correlation_id,
                        'time_to_live_seconds': msg.time_to_live.total_seconds() if msg.time_to_live else None
                    })

            self.logger.info(f"✅ Peeked {len(messages)} messages from {queue_name}")

            return func.HttpResponse(
                body=json.dumps({
                    'queue_name': queue_name,
                    'messages': messages,
                    'count': len(messages),
                    'total_in_queue': total_in_queue,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except ServiceBusError as e:
            self.logger.error(f"❌ Service Bus error: {e}")
            return func.HttpResponse(
                body=json.dumps({
                    'error': f'Service Bus error: {str(e)}',
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=503,
                mimetype='application/json'
            )

        except Exception as e:
            self.logger.error(f"❌ Error peeking messages: {e}")
            self.logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def _peek_deadletter(self, req: func.HttpRequest, queue_name: str) -> func.HttpResponse:
        """
        Peek at dead letter messages (read-only).

        GET /api/admin/servicebus/queues/{queue_name}/deadletter?limit=10

        Query Params:
            limit: Max messages to peek (default: 10, max: 100)

        Args:
            queue_name: Name of the queue

        Returns:
            JSON with array of dead letter messages
        """
        try:
            # Get limit parameter
            limit = int(req.params.get('limit', '10'))
            limit = min(limit, 100)  # Cap at 100

            self.logger.info(f"💀 Peeking {limit} dead letter messages from queue: {queue_name}")

            # Validate queue name
            if queue_name not in self._known_queues:
                return func.HttpResponse(
                    body=json.dumps({
                        'error': f'Unknown queue: {queue_name}',
                        'known_queues': self._known_queues
                    }),
                    status_code=404,
                    mimetype='application/json'
                )

            # Get queue metrics first
            runtime_props = self.admin_client.get_queue_runtime_properties(queue_name)
            total_dead_letters = runtime_props.dead_letter_message_count

            # Peek dead letter messages
            messages = []
            with self.service_bus_client.get_queue_receiver(
                queue_name,
                sub_queue=ServiceBusSubQueue.DEAD_LETTER
            ) as receiver:
                peeked = receiver.peek_messages(max_message_count=limit)

                for msg in peeked:
                    # Get message body
                    try:
                        body_str = str(msg)
                        # Truncate if too long
                        if len(body_str) > 500:
                            body_str = body_str[:500] + "..."
                    except Exception as e:
                        self.logger.debug(f"Could not parse message body: {e}")
                        body_str = "<unable to parse>"

                    messages.append({
                        'sequence_number': msg.sequence_number,
                        'message_id': msg.message_id,
                        'enqueued_time': msg.enqueued_time_utc.isoformat() if msg.enqueued_time_utc else None,
                        'delivery_count': msg.delivery_count,
                        'dead_letter_reason': msg.dead_letter_reason,
                        'dead_letter_error_description': msg.dead_letter_error_description,
                        'content_preview': body_str,
                        'content_type': msg.content_type,
                        'correlation_id': msg.correlation_id
                    })

            self.logger.info(f"✅ Peeked {len(messages)} dead letter messages from {queue_name}")

            return func.HttpResponse(
                body=json.dumps({
                    'queue_name': queue_name,
                    'messages': messages,
                    'count': len(messages),
                    'total_dead_letters': total_dead_letters,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except ServiceBusError as e:
            self.logger.error(f"❌ Service Bus error: {e}")
            return func.HttpResponse(
                body=json.dumps({
                    'error': f'Service Bus error: {str(e)}',
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=503,
                mimetype='application/json'
            )

        except Exception as e:
            self.logger.error(f"❌ Error peeking dead letter messages: {e}")
            self.logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def _get_health(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Get overall Service Bus health metrics.

        GET /api/admin/servicebus/health

        Returns:
            JSON with health status, connection status, and queue health checks
        """
        try:
            self.logger.info("🏥 Checking Service Bus health")

            # Check connection
            connection_status = "connected"
            namespace = self.config.service_bus_namespace or "unknown"

            # Get health for each queue
            queue_health = []
            overall_status = "healthy"
            total_dead_letters = 0

            for queue_name in self._known_queues:
                try:
                    props = self.admin_client.get_queue_runtime_properties(queue_name)

                    active = props.active_message_count
                    dead_letter = props.dead_letter_message_count

                    total_dead_letters += dead_letter

                    # Determine queue status
                    issues = []
                    status = "healthy"

                    if dead_letter > 10:
                        issues.append(f"High dead letter count: {dead_letter}")
                        status = "warning"
                        if overall_status == "healthy":
                            overall_status = "warning"

                    if active > 1000:
                        issues.append(f"High active message count: {active}")
                        status = "warning"
                        if overall_status == "healthy":
                            overall_status = "warning"

                    queue_health.append({
                        'queue_name': queue_name,
                        'status': status,
                        'active_messages': active,
                        'dead_letter_messages': dead_letter,
                        'issues': issues
                    })

                except Exception as e:
                    queue_health.append({
                        'queue_name': queue_name,
                        'status': 'error',
                        'error': str(e)
                    })
                    overall_status = "error"

            # Build health checks
            checks = [
                {
                    'name': 'connection',
                    'status': 'healthy',
                    'message': f'Connected to Service Bus namespace: {namespace}'
                }
            ]

            if total_dead_letters > 0:
                checks.append({
                    'name': 'dead_letter_messages',
                    'status': 'warning' if total_dead_letters < 50 else 'error',
                    'message': f'{total_dead_letters} dead letter messages across {len(self._known_queues)} queues'
                })
            else:
                checks.append({
                    'name': 'dead_letter_messages',
                    'status': 'healthy',
                    'message': 'No dead letter messages'
                })

            result = {
                'status': overall_status,
                'connection': {
                    'status': connection_status,
                    'namespace': namespace
                },
                'queue_health': queue_health,
                'checks': checks,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

            self.logger.info(f"✅ Service Bus health check complete: {overall_status}")

            return func.HttpResponse(
                body=json.dumps(result, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except ServiceBusError as e:
            self.logger.error(f"❌ Service Bus error: {e}")
            return func.HttpResponse(
                body=json.dumps({
                    'status': 'error',
                    'error': f'Service Bus error: {str(e)}',
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=503,
                mimetype='application/json'
            )

        except Exception as e:
            self.logger.error(f"❌ Error checking health: {e}")
            self.logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'status': 'error',
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def _nuke_queue(self, req: func.HttpRequest, queue_name: str) -> func.HttpResponse:
        """
        DESTRUCTIVE: Clear messages from queue (nuclear button).

        POST /api/admin/servicebus/queues/{queue_name}/nuke?confirm=yes&target=all

        Query Params:
            confirm: REQUIRED "yes" for safety
            target: "active" | "deadletter" | "all" (default: all)

        Args:
            queue_name: Name of the queue to clear

        Returns:
            JSON with deleted message counts and operation summary
        """
        try:
            # Safety check: require confirm=yes
            confirm = req.params.get('confirm', '')
            if confirm != 'yes':
                return func.HttpResponse(
                    body=json.dumps({
                        'error': 'Missing required parameter: confirm=yes',
                        'warning': 'This is a DESTRUCTIVE operation that permanently deletes messages',
                        'usage': 'POST /api/admin/servicebus/queues/{queue}/nuke?confirm=yes&target=all'
                    }),
                    status_code=400,
                    mimetype='application/json'
                )

            # Get target parameter
            target = req.params.get('target', 'all').lower()
            if target not in ['active', 'deadletter', 'all']:
                return func.HttpResponse(
                    body=json.dumps({
                        'error': f'Invalid target: {target}',
                        'valid_targets': ['active', 'deadletter', 'all']
                    }),
                    status_code=400,
                    mimetype='application/json'
                )

            self.logger.warning(f"⚠️ NUCLEAR BUTTON: Clearing {target} messages from queue {queue_name}")

            # Validate queue name
            if queue_name not in self._known_queues:
                return func.HttpResponse(
                    body=json.dumps({
                        'error': f'Unknown queue: {queue_name}',
                        'known_queues': self._known_queues
                    }),
                    status_code=404,
                    mimetype='application/json'
                )

            start_time = datetime.now(timezone.utc)
            deleted_active = 0
            deleted_dead_letter = 0

            # Clear active messages if requested
            if target in ['active', 'all']:
                self.logger.warning(f"🗑️ Clearing active messages from {queue_name}")
                with self.service_bus_client.get_queue_receiver(queue_name, max_wait_time=5) as receiver:
                    while True:
                        messages = receiver.receive_messages(max_message_count=100, max_wait_time=5)
                        if not messages:
                            break

                        for msg in messages:
                            receiver.complete_message(msg)
                            deleted_active += 1

                        # Timeout protection
                        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
                        if elapsed > 60:
                            self.logger.warning(f"⏱️ Timeout after 60 seconds, deleted {deleted_active} active messages")
                            break

            # Clear dead letter messages if requested
            if target in ['deadletter', 'all']:
                self.logger.warning(f"🗑️ Clearing dead letter messages from {queue_name}")
                with self.service_bus_client.get_queue_receiver(
                    queue_name,
                    sub_queue=ServiceBusSubQueue.DEAD_LETTER,
                    max_wait_time=5
                ) as receiver:
                    while True:
                        messages = receiver.receive_messages(max_message_count=100, max_wait_time=5)
                        if not messages:
                            break

                        for msg in messages:
                            receiver.complete_message(msg)
                            deleted_dead_letter += 1

                        # Timeout protection
                        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
                        if elapsed > 60:
                            self.logger.warning(f"⏱️ Timeout after 60 seconds, deleted {deleted_dead_letter} dead letter messages")
                            break

            end_time = datetime.now(timezone.utc)
            duration = (end_time - start_time).total_seconds()

            result = {
                'queue_name': queue_name,
                'target': target,
                'deleted': {
                    'active_messages': deleted_active,
                    'dead_letter_messages': deleted_dead_letter,
                    'total': deleted_active + deleted_dead_letter
                },
                'duration_seconds': round(duration, 2),
                'timestamp': end_time.isoformat(),
                'warning': 'This operation is IRREVERSIBLE - messages are permanently deleted'
            }

            self.logger.warning(f"✅ NUKE complete: deleted {deleted_active} active + {deleted_dead_letter} dead letter messages from {queue_name}")

            return func.HttpResponse(
                body=json.dumps(result, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except ServiceBusError as e:
            self.logger.error(f"❌ Service Bus error during nuke: {e}")
            return func.HttpResponse(
                body=json.dumps({
                    'error': f'Service Bus error: {str(e)}',
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=503,
                mimetype='application/json'
            )

        except Exception as e:
            self.logger.error(f"❌ Error during nuke operation: {e}")
            self.logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )


# Create singleton instance for function_app.py to use
servicebus_admin_trigger = ServiceBusAdminTrigger()
