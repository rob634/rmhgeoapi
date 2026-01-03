# ============================================================================
# SERVICE BUS REPOSITORY IMPLEMENTATION
# ============================================================================
# STATUS: Infrastructure - Azure Service Bus messaging
# PURPOSE: High-performance message queue with batch support
# LAST_REVIEWED: 02 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 ref: config/queue_config.py)
# ============================================================================
"""
Service Bus Repository Implementation.

================================================================================
DEPLOYMENT NOTE
================================================================================

Azure Service Bus configuration is in:
    config/queue_config.py (has full Check 8 deployment guide)

This module USES those settings - see queue_config.py for:
    - Service Bus namespace service request template
    - Queue creation (geospatial-jobs, raster-tasks, vector-tasks)
    - Managed identity role assignments (Azure Service Bus Data Owner)
    - Connection string vs managed identity authentication
    - Verification commands

Key Environment Variables (configured in queue_config.py):
    SERVICE_BUS_NAMESPACE: Fully qualified namespace (e.g., myns.servicebus.windows.net)
    SERVICE_BUS_CONNECTION_STRING: Optional connection string for local dev
    SERVICE_BUS_MAX_BATCH_SIZE: Messages per batch (default: 100)
    SERVICE_BUS_RETRY_COUNT: Retry attempts (default: 3)

Queue Names (from queue_config.py):
    - geospatial-jobs: Job orchestration + stage_complete signals
    - raster-tasks: Memory-intensive GDAL operations
    - vector-tasks: Database-bound vector operations

================================================================================

High-performance message repository for Azure Service Bus with batch support.
Designed for scenarios where Queue Storage times out (>1000 messages),
particularly for H3 hexagon processing and container file listing tasks.

Key Features:
    - Batch sending (up to 100 messages per batch)
    - Async support for massive parallelization
    - Automatic retry with exponential backoff
    - Dead letter queue handling
    - Session support for ordered processing
    - Singleton pattern for credential reuse

Performance:
    - Queue Storage: 50ms per message x 1000 = 50 seconds (times out)
    - Service Bus: 100 messages in ~200ms x 10 = 2 seconds total

Exports:
    ServiceBusRepository: Singleton implementation for Service Bus operations

Dependencies:
    azure.servicebus: Service Bus SDK for messaging
    azure.identity: DefaultAzureCredential for authentication
    infrastructure.interface_repository: IQueueRepository interface
    util_logger: Structured logging
"""

from azure.servicebus import ServiceBusClient, ServiceBusMessage, ServiceBusSender, ServiceBusReceiver
from azure.servicebus.aio import ServiceBusClient as AsyncServiceBusClient
from azure.servicebus.management import ServiceBusAdministrationClient, QueueProperties
from azure.servicebus.exceptions import (
    ServiceBusError,                    # Base exception
    ServiceBusConnectionError,          # Connection failures
    ServiceBusCommunicationError,       # Network/firewall issues
    ServiceBusAuthenticationError,      # Auth credential failures
    ServiceBusAuthorizationError,       # Permission denied
    MessageSizeExceededError,           # Message too large (256KB limit)
    MessageLockLostError,               # Lock expired during processing
    MessageAlreadySettled,              # Already completed/abandoned
    MessageNotFoundError,               # Message doesn't exist
    MessagingEntityNotFoundError,       # Queue/topic doesn't exist
    OperationTimeoutError,              # Timeout (transient, retry)
    ServiceBusQuotaExceededError,       # Quota exceeded (permanent)
    ServiceBusServerBusyError,          # Server busy (transient, retry)
    AutoLockRenewTimeout,               # Lock renewal failed (transient)
)
from azure.core.exceptions import ResourceNotFoundError, ResourceExistsError
from azure.identity import DefaultAzureCredential
from azure.core.exceptions import ServiceRequestError
from typing import Optional, List, Dict, Any, Union
import json
import logging
import threading
import asyncio
import time
import os
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
from dataclasses import dataclass

from infrastructure.interface_repository import IQueueRepository
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, "ServiceBusRepository")


@dataclass
class BatchResult:
    """Result of a batch send operation."""
    success: bool
    messages_sent: int
    batch_count: int
    elapsed_ms: float
    errors: List[str] = None


class ServiceBusRepository(IQueueRepository):
    """
    High-performance Service Bus repository with batch support.

    This implementation provides both synchronous and asynchronous operations,
    with special optimizations for batch sending thousands of messages.

    Key Design Decisions:
    - Implements IQueueRepository for compatibility with existing code
    - Adds batch-specific methods for high-volume operations
    - Uses connection pooling for sender/receiver reuse
    - Thread-safe singleton pattern

    Configuration (via environment variables):
    - SERVICE_BUS_NAMESPACE: Service Bus namespace (e.g., "mynamespace")
    - SERVICE_BUS_CONNECTION_STRING: Full connection string (optional, uses DefaultAzureCredential if not provided)
    - SERVICE_BUS_MAX_BATCH_SIZE: Max messages per batch (default: 100)
    - SERVICE_BUS_RETRY_COUNT: Number of retries (default: 3)
    """

    _instance: Optional['ServiceBusRepository'] = None
    _lock = threading.Lock()

    def __new__(cls):
        """Thread-safe singleton creation."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize Service Bus client with credential management."""
        if not hasattr(self, '_initialized'):
            logger.info("🚌 Initializing ServiceBusRepository")

            try:
                # Get configuration from centralized config
                from config import get_config
                config = get_config()

                logger.debug("🔍 Checking Service Bus configuration...")
                logger.debug(f"  Connection string: {'SET' if config.service_bus_connection_string else 'NOT SET'}")
                logger.debug(f"  Namespace: {config.service_bus_namespace or 'NOT SET'}")
                logger.debug(f"  Max batch size: {config.service_bus_max_batch_size}")
                logger.debug(f"  Retry count: {config.service_bus_retry_count}")

                # Check for connection string first (for local development)
                connection_string = config.service_bus_connection_string

                if connection_string:
                    logger.info("🔑 Using connection string authentication")
                    logger.debug(f"Connection string length: {len(connection_string)} chars")

                    try:
                        # SDK retry policy: 5 retries, exponential backoff (14 DEC 2025)
                        self.client = ServiceBusClient.from_connection_string(
                            connection_string,
                            retry_total=5,
                            retry_backoff_factor=0.5,
                            retry_backoff_max=60,
                            retry_mode='exponential'
                        )
                        logger.info("✅ ServiceBusClient created from connection string (retry_total=5)")
                    except Exception as cs_error:
                        logger.error(f"❌ Failed to create client from connection string: {cs_error}")
                        raise

                    self.async_client = None  # Will create on demand
                else:
                    # Use DefaultAzureCredential for production
                    logger.info("🔐 Using DefaultAzureCredential (no connection string found)")

                    # Azure Functions Service Bus configuration
                    fully_qualified_namespace = config.service_bus_namespace

                    if not fully_qualified_namespace:
                        logger.error("❌ Service Bus namespace not configured")
                        logger.error("Please set SERVICE_BUS_NAMESPACE or ServiceBusConnection__fullyQualifiedNamespace")

                        raise ValueError(
                            "ServiceBusConnection__fullyQualifiedNamespace environment variable not set. "
                            "This is required for Azure Functions Service Bus connection. "
                            "Please configure this in Azure Functions Application Settings."
                        )

                    logger.info(f"🚌 Using Service Bus namespace: {fully_qualified_namespace}")

                    # Use DefaultAzureCredential as recommended by Azure docs
                    # This tries managed identity first in Azure Functions
                    logger.info("🔐 Creating DefaultAzureCredential for Service Bus...")
                    try:
                        self.credential = DefaultAzureCredential()
                        logger.info("✅ DefaultAzureCredential created successfully")
                    except Exception as cred_error:
                        logger.error(f"❌ Failed to create DefaultAzureCredential: {cred_error}")
                        raise RuntimeError(f"Credential creation failed: {cred_error}")

                    try:
                        logger.debug(f"📦 Creating ServiceBusClient with namespace: {fully_qualified_namespace}")
                        # SDK retry policy: 5 retries, exponential backoff (14 DEC 2025)
                        self.client = ServiceBusClient(
                            fully_qualified_namespace=fully_qualified_namespace,
                            credential=self.credential,
                            retry_total=5,
                            retry_backoff_factor=0.5,
                            retry_backoff_max=60,
                            retry_mode='exponential'
                        )
                        logger.info("✅ ServiceBusClient created successfully (retry_total=5)")
                    except Exception as client_error:
                        logger.error(f"❌ Failed to create ServiceBusClient: {client_error}")
                        logger.error(f"Namespace used: {fully_qualified_namespace}")
                        raise RuntimeError(f"ServiceBusClient creation failed: {client_error}")

                    # Async client for batch operations
                    try:
                        # SDK retry policy: 5 retries, exponential backoff (14 DEC 2025)
                        self.async_client = AsyncServiceBusClient(
                            fully_qualified_namespace=fully_qualified_namespace,
                            credential=self.credential,
                            retry_total=5,
                            retry_backoff_factor=0.5,
                            retry_backoff_max=60,
                            retry_mode='exponential'
                        )
                        logger.debug("✅ AsyncServiceBusClient created (retry_total=5)")
                    except Exception as async_error:
                        logger.warning(f"⚠️ Failed to create AsyncServiceBusClient: {async_error}")
                        self.async_client = None

                # Configuration
                self.max_batch_size = config.service_bus_max_batch_size
                self.max_retries = config.service_bus_retry_count
                self.retry_delay = 1  # seconds

                # Cache for senders only (senders can be safely reused)
                # NOTE: Receivers are NOT cached - they're lightweight and context managers close them.
                # Creating fresh receivers each time avoids "handler shutdown" errors.
                self._senders: Dict[str, ServiceBusSender] = {}

                self._initialized = True
                logger.info(f"✅ ServiceBusRepository initialized (batch_size={self.max_batch_size})")

            except Exception as e:
                logger.error(f"❌ Failed to initialize ServiceBusRepository: {e}")
                import traceback
                logger.error(f"Full initialization error: {traceback.format_exc()}")
                raise RuntimeError(f"ServiceBusRepository initialization failed: {e}")

    @classmethod
    def instance(cls) -> 'ServiceBusRepository':
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _check_sender_health(self, sender: ServiceBusSender, queue_name: str) -> dict:
        """
        Check sender health and AMQP connection state.

        Returns dict with health status and diagnostic info.
        Added 14 DEC 2025 for debugging message loss issues.

        WARNING: This method accesses private SDK attributes (_running, _shutdown, _handler)
        which are internal implementation details of azure-servicebus SDK.
        These may change in future SDK versions. Uses getattr() with defaults for safety.
        If SDK changes break this, health checks will report "unknown" but app continues working.
        """
        health = {
            "queue": queue_name,
            "healthy": False,
            "running": False,
            "has_handler": False,
            "client_ready": False,
            "shutdown": False,
            "issues": []
        }

        try:
            # Check _running flag
            health["running"] = getattr(sender, '_running', False)
            if not health["running"]:
                health["issues"].append("sender._running is False")

            # Check _shutdown flag
            shutdown_event = getattr(sender, '_shutdown', None)
            if shutdown_event:
                health["shutdown"] = shutdown_event.is_set()
                if health["shutdown"]:
                    health["issues"].append("sender._shutdown is set")

            # Check handler exists
            handler = getattr(sender, '_handler', None)
            health["has_handler"] = handler is not None
            if not handler:
                health["issues"].append("sender._handler is None")
            else:
                # Check client_ready if available
                try:
                    health["client_ready"] = handler.client_ready() if hasattr(handler, 'client_ready') else True
                    if not health["client_ready"]:
                        health["issues"].append("handler.client_ready() is False")
                except Exception as ready_err:
                    health["issues"].append(f"client_ready check failed: {ready_err}")

            # Overall health
            health["healthy"] = (
                health["running"] and
                health["has_handler"] and
                health["client_ready"] and
                not health["shutdown"] and
                len(health["issues"]) == 0
            )

        except Exception as e:
            health["issues"].append(f"Health check error: {e}")

        return health

    def _get_sender(self, queue_or_topic: str) -> ServiceBusSender:
        """
        Get or create a message sender with connection warmup.

        CRITICAL FIX (14 DEC 2025):
        The Azure Service Bus SDK creates senders with lazy AMQP connections.
        If we send a message immediately after creating a sender, the message
        can be lost during AMQP link establishment (SDK reports success but
        message never arrives).

        Solution: Explicitly open the sender connection before caching it.
        This ensures the AMQP link is ATTACHED before any messages are sent.

        ENHANCED (14 DEC 2025): Added health checks and fail-loud behavior.
        """
        # Check if we have a cached sender
        if queue_or_topic in self._senders:
            sender = self._senders[queue_or_topic]

            # ENHANCED: Verify cached sender is healthy before reusing
            health = self._check_sender_health(sender, queue_or_topic)
            if health["healthy"]:
                logger.debug(f"♻️ Reusing healthy sender for queue: {queue_or_topic}")
                return sender
            else:
                # Cached sender is unhealthy - remove and create new one
                logger.warning(
                    f"⚠️ Cached sender unhealthy for {queue_or_topic}, recreating. Issues: {health['issues']}",
                    extra={
                        'queue': queue_or_topic,
                        'sender_health': health,
                        'action': 'recreate_sender'
                    }
                )
                try:
                    sender.close()
                except Exception as close_err:
                    logger.debug(f"Error closing unhealthy sender: {close_err}")
                del self._senders[queue_or_topic]

        # Create new sender
        logger.debug(f"🚌 Creating new sender for queue: {queue_or_topic}")
        try:
            sender = self.client.get_queue_sender(queue_or_topic)
            logger.debug(f"📡 Warming up sender connection (establishing AMQP link)...")

            # CRITICAL: Open the sender connection BEFORE caching
            # This ensures the AMQP link is ATTACHED, not DETACHED
            # Without this, messages sent immediately after creation can be lost
            try:
                # _open() is the SDK's internal method to establish AMQP connection
                # It's safe to call and ensures the link is ready for messages
                sender._open()

                # ENHANCED: Verify warmup succeeded
                health = self._check_sender_health(sender, queue_or_topic)
                if health["healthy"]:
                    logger.info(f"✅ Sender AMQP link established and verified for queue: {queue_or_topic}")
                else:
                    # FAIL LOUD: Don't silently continue with unhealthy sender
                    logger.error(
                        f"❌ Sender warmup completed but health check failed for {queue_or_topic}. Issues: {health['issues']}",
                        extra={
                            'queue': queue_or_topic,
                            'sender_health': health,
                            'error_source': 'infrastructure'
                        }
                    )
                    raise RuntimeError(f"Sender health check failed after warmup: {health['issues']}")

            except Exception as warmup_error:
                # FAIL LOUD: Don't continue with failed warmup
                logger.error(
                    f"❌ Sender warmup FAILED for {queue_or_topic}: {warmup_error}",
                    extra={
                        'queue': queue_or_topic,
                        'error_type': type(warmup_error).__name__,
                        'error_source': 'infrastructure'
                    }
                )
                # Close the failed sender (cleanup - don't let this mask the warmup error)
                try:
                    sender.close()
                except Exception as close_err:
                    logger.debug(f"Failed to close sender during cleanup: {close_err}")
                raise RuntimeError(f"Sender warmup failed for {queue_or_topic}: {warmup_error}")

            logger.debug(f"✅ Sender created and cached for queue: {queue_or_topic}")
            self._senders[queue_or_topic] = sender

        except Exception as sender_error:
            logger.error(f"❌ Failed to create sender for queue '{queue_or_topic}': {sender_error}")
            logger.error(f"Error type: {type(sender_error).__name__}")

            # Check for specific error types
            error_msg = str(sender_error).lower()
            if 'not found' in error_msg or '404' in error_msg:
                logger.error(f"Queue '{queue_or_topic}' does not exist in Service Bus namespace")
            elif 'unauthorized' in error_msg or '401' in error_msg:
                logger.error(f"Authentication failed - check managed identity or connection string")
            elif 'forbidden' in error_msg or '403' in error_msg:
                logger.error(f"Access denied to queue '{queue_or_topic}' - check permissions")

            raise RuntimeError(f"Cannot create sender for queue '{queue_or_topic}': {sender_error}")

        return self._senders[queue_or_topic]

    def _get_receiver(self, queue_or_topic: str) -> ServiceBusReceiver:
        """
        Get a fresh message receiver (no caching).

        Receivers are NOT cached because:
        1. They're closed by context managers (with receiver:)
        2. Creating new receivers is lightweight (just creates a proxy object)
        3. Caching closed receivers causes "handler shutdown" errors

        This is the correct pattern for Service Bus SDK - unlike database connections,
        Service Bus receivers are designed to be created/destroyed frequently.
        """
        logger.debug(f"🚌 Creating fresh receiver for: {queue_or_topic}")
        return self.client.get_queue_receiver(queue_or_topic)

    # ========================================================================
    # IQueueRepository Implementation (for compatibility)
    # ========================================================================

    def send_message(self, queue_name: str, message: BaseModel) -> str:
        """
        Send a single message to Service Bus.

        Implements IQueueRepository interface for compatibility with existing code.
        For high-volume scenarios, use batch_send_messages() instead.

        Args:
            queue_name: Target queue/topic name
            message: Pydantic model to send

        Returns:
            Message ID (generated)
        """
        logger.debug(f"🚌 send_message called for queue: {queue_name}")
        logger.debug(f"📦 Message type: {type(message).__name__}")

        # Step 1: Get sender
        try:
            logger.debug(f"🔌 Getting sender for queue: {queue_name}")
            sender = self._get_sender(queue_name)
            logger.debug(f"✅ Sender obtained successfully")
        except Exception as sender_error:
            logger.error(f"❌ Failed to get sender for {queue_name}: {sender_error}")
            raise RuntimeError(f"Failed to get sender: {str(sender_error)}")

        # Step 2: Serialize message
        try:
            logger.debug(f"📝 Serializing message to JSON")
            message_json = message.model_dump_json()
            logger.debug(f"✅ Message serialized, length: {len(message_json)} chars")
        except Exception as json_error:
            logger.error(f"❌ Failed to serialize message to JSON: {json_error}")
            raise RuntimeError(f"Message serialization failed: {str(json_error)}")

        # Step 3: Create Service Bus message
        try:
            logger.debug(f"📨 Creating ServiceBusMessage object")
            sb_message = ServiceBusMessage(
                body=message_json,
                content_type="application/json",
                time_to_live=timedelta(hours=24),  # Configurable TTL
                application_properties={}  # Initialize properties dict
            )
            logger.debug(f"✅ ServiceBusMessage created successfully")
        except Exception as msg_error:
            logger.error(f"❌ Failed to create ServiceBusMessage: {msg_error}")
            logger.error(f"Message body type: {type(message_json)}, length: {len(message_json) if message_json else 'None'}")
            raise RuntimeError(f"ServiceBusMessage creation failed: {str(msg_error)}")

        # Step 4: Add metadata properties
        try:
            logger.debug(f"🏷️ Adding metadata properties")
            if hasattr(message, 'task_id'):
                logger.debug(f"  Adding task_id: {message.task_id}")
                sb_message.application_properties['task_id'] = message.task_id
            if hasattr(message, 'job_id'):
                logger.debug(f"  Adding job_id: {message.job_id}")
                sb_message.application_properties['job_id'] = message.job_id
            logger.debug(f"✅ Metadata properties added: {sb_message.application_properties}")
        except Exception as prop_error:
            logger.error(f"❌ Failed to add metadata properties: {prop_error}")
            logger.error(f"application_properties type: {type(sb_message.application_properties)}")
            raise RuntimeError(f"Failed to add properties: {str(prop_error)}")

        logger.debug(f"📤 Ready to send message to Service Bus: {queue_name}")

        for attempt in range(self.max_retries):
            try:
                logger.debug(f"📮 Send attempt {attempt + 1}/{self.max_retries}")

                # ENHANCED (14 DEC 2025): Check sender health before each send attempt
                health = self._check_sender_health(sender, queue_name)
                if not health["healthy"]:
                    logger.warning(
                        f"⚠️ Sender unhealthy before send attempt {attempt + 1}. Issues: {health['issues']}",
                        extra={
                            'queue': queue_name,
                            'sender_health': health,
                            'attempt': attempt + 1
                        }
                    )
                    # Try to get a fresh sender
                    if queue_name in self._senders:
                        del self._senders[queue_name]
                    sender = self._get_sender(queue_name)
                    # Re-check health after getting new sender
                    health = self._check_sender_health(sender, queue_name)
                    logger.info(f"🔄 Got fresh sender, health: {health}")

                logger.debug(
                    f"📡 Sender state before send: running={health.get('running')}, "
                    f"has_handler={health.get('has_handler')}, client_ready={health.get('client_ready')}"
                )

                # Step 5: Send the message
                logger.debug(f"📤 Calling send_messages() on queue: {queue_name}")
                send_start = time.time()
                sender.send_messages(sb_message)
                send_elapsed = (time.time() - send_start) * 1000
                logger.debug(f"✅ send_messages() returned in {send_elapsed:.2f}ms")

                # ENHANCED: Check sender health AFTER send to detect issues
                post_health = self._check_sender_health(sender, queue_name)
                if not post_health["healthy"]:
                    logger.warning(
                        f"⚠️ Sender became unhealthy AFTER send! Issues: {post_health['issues']}",
                        extra={
                            'queue': queue_name,
                            'sender_health_post': post_health,
                            'send_elapsed_ms': send_elapsed
                        }
                    )

                # Step 6: Generate message ID for compatibility
                try:
                    message_id = sb_message.message_id or f"sb_{datetime.now(timezone.utc).timestamp()}"

                    # 16 DEC 2025: Extract task_id/job_id for correlation with MESSAGE_RECEIVED logs
                    # TaskQueueMessage has: task_id, parent_job_id
                    # JobQueueMessage has: job_id
                    task_id = getattr(message, 'task_id', None)
                    parent_job_id = getattr(message, 'parent_job_id', None)
                    job_id = getattr(message, 'job_id', None)

                    # Build log message with available IDs
                    id_parts = []
                    if task_id:
                        id_parts.append(f"task={task_id[:16]}...")
                    if parent_job_id:
                        id_parts.append(f"job={parent_job_id[:16]}...")
                    elif job_id:
                        id_parts.append(f"job={job_id[:16]}...")
                    id_summary = ", ".join(id_parts) if id_parts else "no IDs"

                    logger.info(
                        f"✅ Message sent to {queue_name}. ID: {message_id}, {id_summary}, elapsed: {send_elapsed:.2f}ms",
                        extra={
                            'checkpoint': 'MESSAGE_SENT',
                            'queue': queue_name,
                            'message_id': message_id,
                            'task_id': task_id,
                            'parent_job_id': parent_job_id,
                            'job_id': job_id,
                            'send_elapsed_ms': send_elapsed,
                            'sender_healthy_post': post_health.get('healthy', False)
                        }
                    )
                    return message_id
                except Exception as id_error:
                    logger.warning(f"⚠️ Could not get message_id, using timestamp: {id_error}")
                    message_id = f"sb_{datetime.now(timezone.utc).timestamp()}"
                    return message_id

            # === PERMANENT ERRORS (28 NOV 2025) - Never retry, fail immediately ===
            except (ServiceBusAuthenticationError, ServiceBusAuthorizationError) as e:
                # Auth failures won't resolve with retry
                logger.error(
                    f"❌ Authentication/Authorization failed for {queue_name}: {e}",
                    extra={
                        'error_source': 'infrastructure',  # 29 NOV 2025: For Application Insights filtering
                        'queue': queue_name,
                        'error_type': type(e).__name__,
                        'retryable': False,
                        'error_category': 'auth'
                    }
                )
                raise RuntimeError(f"Service Bus auth failed: {e}")

            except MessageSizeExceededError as e:
                # Message too large (256KB limit) - won't fix with retry
                logger.error(
                    f"❌ Message too large for {queue_name}: {e}",
                    extra={
                        'error_source': 'infrastructure',  # 29 NOV 2025: For Application Insights filtering
                        'queue': queue_name,
                        'error_type': 'MessageSizeExceededError',
                        'retryable': False,
                        'error_category': 'validation',
                        'message_type': type(message).__name__
                    }
                )
                raise RuntimeError(f"Message exceeds 256KB limit: {e}")

            except MessagingEntityNotFoundError as e:
                # Queue doesn't exist - configuration error
                logger.error(
                    f"❌ Queue '{queue_name}' not found: {e}",
                    extra={
                        'error_source': 'infrastructure',  # 29 NOV 2025: For Application Insights filtering
                        'queue': queue_name,
                        'error_type': 'MessagingEntityNotFoundError',
                        'retryable': False,
                        'error_category': 'config'
                    }
                )
                raise RuntimeError(f"Queue '{queue_name}' does not exist: {e}")

            except ServiceBusQuotaExceededError as e:
                # Quota exceeded - needs manual intervention
                logger.error(
                    f"❌ Service Bus quota exceeded for {queue_name}: {e}",
                    extra={
                        'error_source': 'infrastructure',  # 29 NOV 2025: For Application Insights filtering
                        'queue': queue_name,
                        'error_type': 'ServiceBusQuotaExceededError',
                        'retryable': False,
                        'error_category': 'quota'
                    }
                )
                raise RuntimeError(f"Service Bus quota exceeded: {e}")

            # === TRANSIENT ERRORS - Retry with backoff ===
            except (OperationTimeoutError, ServiceBusServerBusyError, ServiceBusConnectionError, ServiceBusCommunicationError) as e:
                error_type = type(e).__name__
                logger.warning(
                    f"⚠️ Transient error on attempt {attempt + 1}/{self.max_retries}: {error_type}",
                    extra={
                        'queue': queue_name,
                        'error_type': error_type,
                        'retryable': True,
                        'error_category': 'transient',
                        'attempt': attempt + 1
                    }
                )

                if attempt == self.max_retries - 1:
                    logger.error(
                        f"❌ Failed to send message after {self.max_retries} attempts (transient errors)",
                        extra={
                            'error_source': 'infrastructure',  # 29 NOV 2025: For Application Insights filtering
                            'queue': queue_name,
                            'error_type': error_type,
                            'final_error': str(e)
                        }
                    )
                    raise RuntimeError(f"Failed to send to {queue_name} after retries: {e}")

                wait_time = self.retry_delay * (2 ** attempt)
                logger.debug(f"⏳ Waiting {wait_time} seconds before retry...")
                time.sleep(wait_time)

            # === UNEXPECTED ERRORS - Log full context, then retry ===
            except ServiceBusError as e:
                # Catch-all for other Service Bus errors
                error_type = type(e).__name__
                logger.warning(
                    f"⚠️ ServiceBusError on attempt {attempt + 1}/{self.max_retries}: {error_type}: {e}",
                    extra={
                        'queue': queue_name,
                        'error_type': error_type,
                        'retryable': True,
                        'error_category': 'service_bus_other',
                        'attempt': attempt + 1
                    }
                )

                if attempt == self.max_retries - 1:
                    logger.error(f"❌ Failed to send message after {self.max_retries} attempts: {e}")
                    raise RuntimeError(f"Failed to send to {queue_name}: {e}")

                wait_time = self.retry_delay * (2 ** attempt)
                time.sleep(wait_time)

            except Exception as e:
                # Non-Service Bus errors (serialization, etc.)
                error_type = type(e).__name__
                logger.error(
                    f"❌ Unexpected error sending to {queue_name}: {error_type}: {e}",
                    extra={
                        'error_source': 'infrastructure',  # 29 NOV 2025: For Application Insights filtering
                        'queue': queue_name,
                        'error_type': error_type,
                        'retryable': False,
                        'error_category': 'unexpected'
                    }
                )
                raise RuntimeError(f"Unexpected error sending to {queue_name}: {e}")

    def send_message_with_delay(
        self,
        queue_name: str,
        message: BaseModel,
        delay_seconds: int
    ) -> str:
        """
        Send a message to Service Bus with scheduled delivery (exponential backoff retry).

        Uses Service Bus ScheduledEnqueueTimeUtc to delay message delivery.
        This is used for task retry with exponential backoff.

        Args:
            queue_name: Target queue name
            message: Pydantic model to send (TaskQueueMessage)
            delay_seconds: Number of seconds to delay delivery

        Returns:
            Message ID
        """
        logger.info(f"⏰ Scheduling message for delivery in {delay_seconds}s to queue: {queue_name}")

        # Calculate scheduled delivery time
        scheduled_time = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
        logger.debug(f"📅 Scheduled delivery: {scheduled_time.isoformat()}")

        # Get sender
        sender = self._get_sender(queue_name)

        # Serialize message
        message_json = message.model_dump_json()

        # Create Service Bus message with scheduled time
        sb_message = ServiceBusMessage(
            body=message_json,
            content_type="application/json",
            time_to_live=timedelta(hours=24),
            scheduled_enqueue_time_utc=scheduled_time  # KEY: Delay delivery
        )

        # Initialize application_properties (it's None by default)
        sb_message.application_properties = {}

        # Add metadata properties
        if hasattr(message, 'task_id'):
            sb_message.application_properties['task_id'] = message.task_id
        if hasattr(message, 'job_id'):
            sb_message.application_properties['job_id'] = message.job_id

        # Send the message
        sender.send_messages(sb_message)

        message_id = sb_message.message_id or f"sb_{datetime.now(timezone.utc).timestamp()}"
        logger.info(f"✅ Message scheduled for {scheduled_time.isoformat()} - ID: {message_id}")

        return message_id

    def receive_messages(
        self,
        queue_name: str,
        max_messages: int = 1,
        visibility_timeout: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Receive messages from Service Bus.

        Args:
            queue_name: Queue to receive from
            max_messages: Maximum messages to receive
            visibility_timeout: Not used (Service Bus uses lock duration)

        Returns:
            List of message dictionaries
        """
        receiver = self._get_receiver(queue_name)

        try:
            with receiver:
                messages = receiver.receive_messages(
                    max_message_count=max_messages,
                    max_wait_time=5
                )

                result = []
                for msg in messages:
                    # Parse message body with explicit error handling (28 NOV 2025)
                    # Malformed messages are logged and skipped rather than crashing
                    try:
                        message_data = json.loads(str(msg))
                    except json.JSONDecodeError as e:
                        logger.error(
                            f"❌ Failed to deserialize Service Bus message: {e}",
                            extra={
                                'error_source': 'infrastructure',  # 29 NOV 2025: For Application Insights filtering
                                'queue': queue_name,
                                'message_id': msg.message_id,
                                'error_type': 'JSONDecodeError',
                                'delivery_count': msg.delivery_count,
                                'preview': str(msg)[:200]
                            }
                        )
                        # Dead-letter this malformed message
                        try:
                            receiver.dead_letter_message(msg, reason="JSONDecodeError", error_description=str(e))
                            logger.warning(f"📤 Dead-lettered malformed message {msg.message_id}")
                        except Exception as dl_error:
                            logger.error(f"❌ Failed to dead-letter message: {dl_error}")
                        continue  # Skip to next message

                    result.append({
                        'id': msg.message_id,
                        'content': message_data,
                        'sequence_number': msg.sequence_number,
                        'delivery_count': msg.delivery_count,
                        'enqueued_time': msg.enqueued_time_utc.isoformat() if msg.enqueued_time_utc else None,
                        'properties': dict(msg.application_properties) if msg.application_properties else {},
                        '_receiver': receiver,  # Keep for completing/abandoning
                        '_message': msg
                    })

                logger.info(f"📥 Received {len(result)} messages from {queue_name}")
                return result

        # === Specific exception handling for receive operations (28 NOV 2025) ===
        except (ServiceBusAuthenticationError, ServiceBusAuthorizationError) as e:
            logger.error(
                f"❌ Auth failed receiving from {queue_name}: {e}",
                extra={
                    'error_source': 'infrastructure',  # 29 NOV 2025: For Application Insights filtering
                    'queue': queue_name,
                    'error_type': type(e).__name__,
                    'retryable': False,
                    'error_category': 'auth'
                }
            )
            raise RuntimeError(f"Service Bus auth failed: {e}")

        except MessagingEntityNotFoundError as e:
            logger.error(
                f"❌ Queue '{queue_name}' not found: {e}",
                extra={
                    'error_source': 'infrastructure',  # 29 NOV 2025: For Application Insights filtering
                    'queue': queue_name,
                    'error_type': 'MessagingEntityNotFoundError',
                    'retryable': False,
                    'error_category': 'config'
                }
            )
            raise RuntimeError(f"Queue '{queue_name}' does not exist: {e}")

        except (OperationTimeoutError, ServiceBusServerBusyError) as e:
            # Transient - caller may retry
            logger.warning(
                f"⚠️ Transient error receiving from {queue_name}: {type(e).__name__}",
                extra={
                    'queue': queue_name,
                    'error_type': type(e).__name__,
                    'retryable': True,
                    'error_category': 'transient'
                }
            )
            raise  # Let caller decide to retry

        except (ServiceBusConnectionError, ServiceBusCommunicationError) as e:
            # Connection issues - may need reconnect
            logger.error(
                f"❌ Connection error receiving from {queue_name}: {e}",
                extra={
                    'error_source': 'infrastructure',  # 29 NOV 2025: For Application Insights filtering
                    'queue': queue_name,
                    'error_type': type(e).__name__,
                    'retryable': True,
                    'error_category': 'connection'
                }
            )
            raise

        except ServiceBusError as e:
            # Other Service Bus errors
            logger.error(
                f"❌ ServiceBusError receiving from {queue_name}: {type(e).__name__}: {e}",
                extra={
                    'error_source': 'infrastructure',  # 29 NOV 2025: For Application Insights filtering
                    'queue': queue_name,
                    'error_type': type(e).__name__,
                    'error_category': 'service_bus_other'
                }
            )
            raise

        except Exception as e:
            logger.error(
                f"❌ Unexpected error receiving from {queue_name}: {type(e).__name__}: {e}",
                extra={
                    'error_source': 'infrastructure',  # 29 NOV 2025: For Application Insights filtering
                    'queue': queue_name,
                    'error_type': type(e).__name__,
                    'error_category': 'unexpected'
                }
            )
            raise

    def delete_message(self, queue_name: str, message_id: str, pop_receipt: str = None) -> bool:
        """
        Complete a message (remove from queue).

        Note: pop_receipt parameter ignored (for Queue Storage compatibility).
        Message completion requires the actual message object.

        Args:
            queue_name: Queue containing the message
            message_id: Message ID (used to find message)
            pop_receipt: Ignored (Queue Storage compatibility)

        Returns:
            True if completed successfully
        """
        # Note: This is a simplified implementation
        # In production, you'd need to track message objects for completion
        logger.warning("⚠️ Message completion requires message object from receive_messages()")
        return True

    def peek_messages(self, queue_name: str, max_messages: int = 1) -> List[Dict[str, Any]]:
        """
        Peek at messages without removing them.

        Args:
            queue_name: Queue to peek at
            max_messages: Maximum messages to peek

        Returns:
            List of message dictionaries
        """
        receiver = self._get_receiver(queue_name)

        try:
            with receiver:
                messages = receiver.peek_messages(max_message_count=max_messages)

                result = []
                for msg in messages:
                    # Parse message body with explicit error handling (28 NOV 2025)
                    try:
                        message_data = json.loads(str(msg))
                    except json.JSONDecodeError as e:
                        logger.error(
                            f"❌ Failed to deserialize peeked message: {e}",
                            extra={
                                'error_source': 'infrastructure',  # 29 NOV 2025: For Application Insights filtering
                                'queue': queue_name,
                                'message_id': msg.message_id,
                                'error_type': 'JSONDecodeError',
                                'preview': str(msg)[:200]
                            }
                        )
                        continue  # Skip malformed message in peek results

                    result.append({
                        'id': msg.message_id,
                        'content': message_data,
                        'sequence_number': msg.sequence_number,
                        'enqueued_time': msg.enqueued_time_utc.isoformat() if msg.enqueued_time_utc else None
                    })

                logger.debug(f"👀 Peeked at {len(result)} messages in {queue_name}")
                return result

        # === Specific exception handling for peek operations (28 NOV 2025) ===
        except (ServiceBusAuthenticationError, ServiceBusAuthorizationError) as e:
            logger.error(
                f"❌ Auth failed peeking {queue_name}: {e}",
                extra={
                    'error_source': 'infrastructure',  # 29 NOV 2025: For Application Insights filtering
                    'queue': queue_name,
                    'error_type': type(e).__name__,
                    'retryable': False,
                    'error_category': 'auth'
                }
            )
            raise RuntimeError(f"Service Bus auth failed: {e}")

        except MessagingEntityNotFoundError as e:
            logger.error(
                f"❌ Queue '{queue_name}' not found for peek: {e}",
                extra={
                    'error_source': 'infrastructure',  # 29 NOV 2025: For Application Insights filtering
                    'queue': queue_name,
                    'error_type': 'MessagingEntityNotFoundError',
                    'retryable': False,
                    'error_category': 'config'
                }
            )
            raise RuntimeError(f"Queue '{queue_name}' does not exist: {e}")

        except (OperationTimeoutError, ServiceBusServerBusyError, ServiceBusConnectionError, ServiceBusCommunicationError) as e:
            logger.warning(
                f"⚠️ Transient error peeking {queue_name}: {type(e).__name__}",
                extra={
                    'queue': queue_name,
                    'error_type': type(e).__name__,
                    'retryable': True,
                    'error_category': 'transient'
                }
            )
            raise

        except ServiceBusError as e:
            logger.error(
                f"❌ ServiceBusError peeking {queue_name}: {type(e).__name__}: {e}",
                extra={
                    'error_source': 'infrastructure',  # 29 NOV 2025: For Application Insights filtering
                    'queue': queue_name,
                    'error_type': type(e).__name__,
                    'error_category': 'service_bus_other'
                }
            )
            raise

        except Exception as e:
            logger.error(
                f"❌ Unexpected error peeking {queue_name}: {type(e).__name__}: {e}",
                extra={
                    'error_source': 'infrastructure',  # 29 NOV 2025: For Application Insights filtering
                    'queue': queue_name,
                    'error_type': type(e).__name__,
                    'error_category': 'unexpected'
                }
            )
            raise

    def message_exists_for_task(self, queue_name: str, task_id: str, max_peek: int = 100) -> bool:
        """
        Check if a message exists in the queue for a specific task.

        Peeks at messages (without removing them) and searches for a message
        with matching task_id. Used by janitor to verify if message was lost
        before re-queuing orphaned tasks.

        Args:
            queue_name: Queue to search
            task_id: Task ID to look for
            max_peek: Maximum messages to peek (default 100)

        Returns:
            True if message found, False if not found

        Note:
            - Peek is limited, so very deep queue messages may not be found
            - False negative possible if message is beyond max_peek depth
            - This is a best-effort check, not a guarantee
        """
        logger.debug(
            f"[JANITOR] 🔍 Searching queue '{queue_name}' for task_id={task_id[:16]}... "
            f"(max_peek={max_peek})"
        )

        try:
            messages = self.peek_messages(queue_name, max_messages=max_peek)

            for msg in messages:
                content = msg.get('content', {})
                msg_task_id = content.get('task_id', '')

                if msg_task_id == task_id:
                    logger.info(
                        f"[JANITOR] ✅ Message FOUND for task_id={task_id[:16]}... "
                        f"in queue '{queue_name}' (sequence={msg.get('sequence_number')})"
                    )
                    return True

            logger.info(
                f"[JANITOR] ❌ Message NOT FOUND for task_id={task_id[:16]}... "
                f"in queue '{queue_name}' (searched {len(messages)} messages)"
            )
            return False

        except Exception as e:
            # On error, assume message might exist to avoid duplicate sends
            logger.warning(
                f"[JANITOR] ⚠️ Error checking queue '{queue_name}' for task_id={task_id[:16]}...: {e}. "
                f"Assuming message exists to avoid duplicates."
            )
            return True  # Safe default: don't re-queue if we can't check

    def get_queue_length(self, queue_name: str) -> int:
        """
        Get approximate number of messages in queue.

        Note: Service Bus doesn't provide direct message count.
        This is an approximation based on peeking.

        Args:
            queue_name: Queue to check

        Returns:
            Approximate message count
        """
        # Service Bus doesn't provide direct count
        # This is a workaround by peeking
        messages = self.peek_messages(queue_name, max_messages=100)
        count = len(messages)

        if count == 100:
            logger.warning(f"Queue {queue_name} has 100+ messages (exact count unavailable)")

        return count

    def clear_queue(self, queue_name: str) -> bool:
        """
        Clear all messages from queue.

        WARNING: This receives and completes all messages. Very expensive operation.

        Args:
            queue_name: Queue to clear

        Returns:
            True if cleared successfully
        """
        logger.warning(f"🗑️ Clearing queue {queue_name} (expensive operation!)")

        receiver = self._get_receiver(queue_name)
        cleared_count = 0

        try:
            with receiver:
                while True:
                    messages = receiver.receive_messages(
                        max_message_count=100,
                        max_wait_time=1
                    )

                    if not messages:
                        break

                    for msg in messages:
                        receiver.complete_message(msg)
                        cleared_count += 1

                    logger.debug(f"Cleared {cleared_count} messages so far...")

            logger.warning(f"🗑️ Cleared {cleared_count} messages from {queue_name}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to clear queue {queue_name}: {e}")
            return False

    # ========================================================================
    # Queue Management Methods (08 DEC 2025 - Multi-Function App Architecture)
    # ========================================================================

    def _get_admin_client(self) -> ServiceBusAdministrationClient:
        """
        Get Service Bus Administration Client for queue management operations.

        Creates admin client on demand for operations like queue creation/verification.
        Uses same authentication method as messaging client.
        """
        from config import get_config
        config = get_config()

        connection_string = config.service_bus_connection_string
        if connection_string:
            return ServiceBusAdministrationClient.from_connection_string(connection_string)
        else:
            fully_qualified_namespace = config.service_bus_namespace
            if not fully_qualified_namespace:
                raise ValueError("Service Bus namespace not configured")
            return ServiceBusAdministrationClient(
                fully_qualified_namespace=fully_qualified_namespace,
                credential=DefaultAzureCredential()
            )

    def queue_exists(self, queue_name: str) -> bool:
        """
        Check if a Service Bus queue exists.

        Args:
            queue_name: Name of the queue to check

        Returns:
            True if queue exists, False otherwise
        """
        try:
            admin_client = self._get_admin_client()
            with admin_client:
                queue = admin_client.get_queue(queue_name)
                return queue is not None
        except ResourceNotFoundError:
            return False
        except Exception as e:
            logger.error(f"❌ Error checking queue existence '{queue_name}': {e}")
            raise

    def ensure_queue_exists(
        self,
        queue_name: str,
        lock_duration_minutes: int = 5,
        max_delivery_count: int = 1,
        default_ttl_days: int = 7
    ) -> Dict[str, Any]:
        """
        Ensure a Service Bus queue exists, creating it if necessary.

        This method is critical for Multi-Function App Architecture to ensure
        raster-tasks and vector-tasks queues exist before routing tasks.

        Args:
            queue_name: Name of the queue to ensure exists
            lock_duration_minutes: Message lock duration (default: 5 min for raster, 2 min for vector)
            max_delivery_count: Max retries before dead-letter (default: 1)
            default_ttl_days: Message time-to-live in days (default: 7)

        Returns:
            Dict with operation result:
            - queue_name: Name of queue
            - exists: True if queue existed or was created
            - created: True if queue was created, False if it already existed
            - properties: Queue properties (if accessible)
            - error: Error message if operation failed
        """
        logger.info(f"🔍 Ensuring queue exists: {queue_name}")

        try:
            admin_client = self._get_admin_client()
            with admin_client:
                # Check if queue exists
                try:
                    queue_props = admin_client.get_queue(queue_name)
                    logger.info(f"✅ Queue '{queue_name}' already exists")
                    return {
                        "queue_name": queue_name,
                        "exists": True,
                        "created": False,
                        "properties": {
                            "lock_duration": str(queue_props.lock_duration),
                            "max_delivery_count": queue_props.max_delivery_count,
                            "default_message_time_to_live": str(queue_props.default_message_time_to_live),
                            "max_size_in_megabytes": queue_props.max_size_in_megabytes
                        }
                    }

                except ResourceNotFoundError:
                    # Queue doesn't exist - create it
                    logger.info(f"📝 Queue '{queue_name}' not found, creating...")

                    from datetime import timedelta

                    queue_props = admin_client.create_queue(
                        queue_name,
                        lock_duration=timedelta(minutes=lock_duration_minutes),
                        max_delivery_count=max_delivery_count,
                        default_message_time_to_live=timedelta(days=default_ttl_days),
                        dead_lettering_on_message_expiration=True
                    )

                    logger.info(f"✅ Queue '{queue_name}' created successfully")
                    return {
                        "queue_name": queue_name,
                        "exists": True,
                        "created": True,
                        "properties": {
                            "lock_duration": str(queue_props.lock_duration),
                            "max_delivery_count": queue_props.max_delivery_count,
                            "default_message_time_to_live": str(queue_props.default_message_time_to_live),
                            "max_size_in_megabytes": queue_props.max_size_in_megabytes
                        }
                    }

        except ResourceExistsError:
            # Race condition - queue was created between check and create
            logger.info(f"✅ Queue '{queue_name}' exists (race condition handled)")
            return {
                "queue_name": queue_name,
                "exists": True,
                "created": False,
                "note": "Queue created by another process"
            }

        except Exception as e:
            logger.error(f"❌ Failed to ensure queue '{queue_name}': {e}")
            return {
                "queue_name": queue_name,
                "exists": False,
                "created": False,
                "error": str(e),
                "error_type": type(e).__name__
            }

    def ensure_all_queues_exist(self) -> Dict[str, Any]:
        """
        Ensure all required Service Bus queues exist for Multi-Function App Architecture.

        Creates the following queues if missing (11 DEC 2025 - No Legacy Fallbacks):
        - geospatial-jobs: Job orchestration + stage_complete signals
        - raster-tasks: Raster task processing (memory-intensive, longer lock)
        - vector-tasks: Vector task processing (high concurrency, shorter lock)

        Returns:
            Dict with results for each queue
        """
        from config import get_config
        config = get_config()

        logger.info("🚌 Ensuring all required Service Bus queues exist...")

        # Queue configurations (11 DEC 2025 - No Legacy Fallbacks, 3 queues only)
        queue_configs = [
            {
                "name": config.service_bus_jobs_queue,  # geospatial-jobs
                "lock_duration_minutes": 5,
                "max_delivery_count": 1,
                "purpose": "Job orchestration and stage_complete signals"
            },
            {
                "name": config.queues.raster_tasks_queue,  # raster-tasks
                "lock_duration_minutes": 5,  # Longer lock for GDAL operations
                "max_delivery_count": 1,
                "purpose": "Raster task processing (memory-intensive GDAL ops)"
            },
            {
                "name": config.queues.vector_tasks_queue,  # vector-tasks
                "lock_duration_minutes": 2,  # Shorter lock for faster vector ops
                "max_delivery_count": 1,
                "purpose": "Vector task processing (high concurrency)"
            }
        ]

        results = {
            "queues_checked": len(queue_configs),
            "queues_created": 0,
            "queues_existed": 0,
            "errors": [],
            "queue_results": {}
        }

        for queue_config in queue_configs:
            queue_name = queue_config["name"]
            result = self.ensure_queue_exists(
                queue_name=queue_name,
                lock_duration_minutes=queue_config["lock_duration_minutes"],
                max_delivery_count=queue_config["max_delivery_count"]
            )

            result["purpose"] = queue_config["purpose"]
            results["queue_results"][queue_name] = result

            if result.get("created"):
                results["queues_created"] += 1
            elif result.get("exists"):
                results["queues_existed"] += 1
            elif result.get("error"):
                results["errors"].append({
                    "queue": queue_name,
                    "error": result["error"]
                })

        results["all_queues_ready"] = (
            results["queues_created"] + results["queues_existed"] == results["queues_checked"]
        )

        if results["all_queues_ready"]:
            logger.info(f"✅ All {results['queues_checked']} queues ready "
                       f"({results['queues_existed']} existed, {results['queues_created']} created)")
        else:
            logger.error(f"❌ Queue verification failed: {len(results['errors'])} errors")

        return results

    # ========================================================================
    # Service Bus Specific Methods (High-Volume Operations)
    # ========================================================================

    def batch_send_messages(
        self,
        queue_name: str,
        messages: List[BaseModel],
        batch_size: Optional[int] = None
    ) -> BatchResult:
        """
        Send messages in batches for high performance.

        This is the key method for high-volume scenarios like H3 hexagon processing.
        Sends messages in batches of up to 100 (Service Bus limit).

        Args:
            queue_name: Target queue/topic
            messages: List of Pydantic models to send
            batch_size: Override default batch size (max 100)

        Returns:
            BatchResult with statistics

        Example:
            # Send 10,000 task messages
            tasks = [TaskQueueMessage(...) for _ in range(10000)]
            result = repo.batch_send_messages("tasks", tasks)
            print(f"Sent {result.messages_sent} messages in {result.elapsed_ms}ms")
        """
        start_time = time.time()
        batch_size = min(batch_size or self.max_batch_size, 100)  # Service Bus limit

        logger.info(f"📦 Batch sending {len(messages)} messages to {queue_name}")
        logger.debug(f"Batch size: {batch_size}")

        sender = self._get_sender(queue_name)
        messages_sent = 0
        batch_count = 0
        errors = []

        try:
            # Don't use context manager with cached sender
            # Process messages in batches
            for i in range(0, len(messages), batch_size):
                batch = messages[i:i + batch_size]
                batch_count += 1

                # Convert to Service Bus messages
                sb_messages = []
                for msg in batch:
                    sb_message = ServiceBusMessage(
                        body=msg.model_dump_json(),
                        content_type="application/json"
                    )

                    # Add metadata for tracing
                    if hasattr(msg, 'task_id'):
                        sb_message.application_properties['task_id'] = msg.task_id
                    if hasattr(msg, 'job_id'):
                        sb_message.application_properties['job_id'] = msg.job_id

                    sb_messages.append(sb_message)

                # Send batch with retry and specific exception handling (28 NOV 2025)
                for attempt in range(self.max_retries):
                    try:
                        sender.send_messages(sb_messages)
                        messages_sent += len(sb_messages)

                        if batch_count % 10 == 0:
                            logger.debug(f"Progress: {messages_sent}/{len(messages)} messages sent")
                        break

                    # === PERMANENT ERRORS - Stop entire batch operation ===
                    except (ServiceBusAuthenticationError, ServiceBusAuthorizationError) as e:
                        logger.error(
                            f"❌ Auth failed on batch {batch_count}: {e}",
                            extra={
                                'error_source': 'infrastructure',  # 29 NOV 2025: For Application Insights filtering
                                'queue': queue_name,
                                'error_type': type(e).__name__,
                                'retryable': False,
                                'error_category': 'auth',
                                'batch_number': batch_count,
                                'messages_sent_so_far': messages_sent
                            }
                        )
                        # Auth errors affect all batches - abort entirely
                        raise RuntimeError(f"Service Bus auth failed during batch: {e}")

                    except MessagingEntityNotFoundError as e:
                        logger.error(
                            f"❌ Queue '{queue_name}' not found during batch: {e}",
                            extra={
                                'error_source': 'infrastructure',  # 29 NOV 2025: For Application Insights filtering
                                'queue': queue_name,
                                'error_type': 'MessagingEntityNotFoundError',
                                'retryable': False,
                                'error_category': 'config'
                            }
                        )
                        raise RuntimeError(f"Queue '{queue_name}' does not exist: {e}")

                    except ServiceBusQuotaExceededError as e:
                        logger.error(
                            f"❌ Quota exceeded at batch {batch_count}: {e}",
                            extra={
                                'error_source': 'infrastructure',  # 29 NOV 2025: For Application Insights filtering
                                'queue': queue_name,
                                'error_type': 'ServiceBusQuotaExceededError',
                                'retryable': False,
                                'error_category': 'quota',
                                'messages_sent_so_far': messages_sent
                            }
                        )
                        # Return partial success - some messages sent before quota hit
                        errors.append(f"Batch {batch_count}: Quota exceeded - {e}")
                        break  # Stop processing more batches

                    except MessageSizeExceededError as e:
                        logger.error(
                            f"❌ Batch {batch_count} message too large: {e}",
                            extra={
                                'error_source': 'infrastructure',  # 29 NOV 2025: For Application Insights filtering
                                'queue': queue_name,
                                'error_type': 'MessageSizeExceededError',
                                'retryable': False,
                                'error_category': 'validation',
                                'batch_number': batch_count
                            }
                        )
                        errors.append(f"Batch {batch_count}: Message size exceeded")
                        break  # Skip this batch, continue with next

                    # === TRANSIENT ERRORS - Retry this batch ===
                    except (OperationTimeoutError, ServiceBusServerBusyError, ServiceBusConnectionError, ServiceBusCommunicationError) as e:
                        error_type = type(e).__name__
                        logger.warning(
                            f"⚠️ Transient error on batch {batch_count}, attempt {attempt + 1}: {error_type}",
                            extra={
                                'queue': queue_name,
                                'error_type': error_type,
                                'retryable': True,
                                'error_category': 'transient',
                                'batch_number': batch_count,
                                'attempt': attempt + 1
                            }
                        )

                        if attempt == self.max_retries - 1:
                            errors.append(f"Batch {batch_count} failed after {self.max_retries} retries: {error_type}")
                            logger.error(f"❌ Batch {batch_count} failed after retries: {e}")
                        else:
                            time.sleep(self.retry_delay * (2 ** attempt))

                    # === OTHER SERVICE BUS ERRORS - Retry ===
                    except ServiceBusError as e:
                        error_type = type(e).__name__
                        if attempt == self.max_retries - 1:
                            errors.append(f"Batch {batch_count}: {error_type} - {e}")
                            logger.error(f"❌ Batch {batch_count} ServiceBusError: {e}")
                        else:
                            logger.warning(f"⚠️ Batch {batch_count} attempt {attempt + 1}: {error_type}")
                            time.sleep(self.retry_delay * (2 ** attempt))

                    # === UNEXPECTED ERRORS - Log and continue ===
                    except Exception as e:
                        error_type = type(e).__name__
                        logger.error(
                            f"❌ Unexpected error on batch {batch_count}: {error_type}: {e}",
                            extra={
                                'error_source': 'infrastructure',  # 29 NOV 2025: For Application Insights filtering
                                'queue': queue_name,
                                'error_type': error_type,
                                'retryable': False,
                                'error_category': 'unexpected',
                                'batch_number': batch_count
                            }
                        )
                        errors.append(f"Batch {batch_count}: Unexpected {error_type} - {e}")
                        break  # Don't retry unexpected errors

            elapsed_ms = (time.time() - start_time) * 1000

            result = BatchResult(
                success=len(errors) == 0,
                messages_sent=messages_sent,
                batch_count=batch_count,
                elapsed_ms=elapsed_ms,
                errors=errors if errors else None
            )

            # 16 DEC 2025: Extract sample task_id/job_id for correlation
            sample_task_id = None
            sample_job_id = None
            if messages:
                first_msg = messages[0]
                sample_task_id = getattr(first_msg, 'task_id', None)
                sample_job_id = getattr(first_msg, 'parent_job_id', None) or getattr(first_msg, 'job_id', None)

            logger.info(
                f"✅ Batch send complete: {messages_sent}/{len(messages)} messages "
                f"in {batch_count} batches, {elapsed_ms:.2f}ms",
                extra={
                    'checkpoint': 'BATCH_SENT',
                    'queue': queue_name,
                    'messages_sent': messages_sent,
                    'messages_total': len(messages),
                    'batch_count': batch_count,
                    'elapsed_ms': elapsed_ms,
                    'sample_task_id': sample_task_id,
                    'sample_job_id': sample_job_id
                }
            )

            return result

        except Exception as e:
            logger.error(f"❌ Batch send failed: {e}")
            elapsed_ms = (time.time() - start_time) * 1000
            return BatchResult(
                success=False,
                messages_sent=messages_sent,
                batch_count=batch_count,
                elapsed_ms=elapsed_ms,
                errors=[str(e)]
            )

    async def async_batch_send_messages(
        self,
        queue_name: str,
        messages: List[BaseModel],
        batch_size: Optional[int] = None
    ) -> BatchResult:
        """
        Asynchronously send messages in batches.

        For maximum performance with very large message volumes.

        Args:
            queue_name: Target queue/topic
            messages: List of Pydantic models to send
            batch_size: Override default batch size

        Returns:
            BatchResult with statistics
        """
        if not self.async_client:
            logger.warning("Async client not available, falling back to sync")
            return self.batch_send_messages(queue_name, messages, batch_size)

        start_time = time.time()
        batch_size = min(batch_size or self.max_batch_size, 100)

        async with self.async_client:
            sender = self.async_client.get_queue_sender(queue_name)
            async with sender:
                messages_sent = 0
                batch_count = 0
                errors = []

                # Create batches
                for i in range(0, len(messages), batch_size):
                    batch = messages[i:i + batch_size]
                    batch_count += 1

                    # Convert to Service Bus messages
                    sb_messages = []
                    for msg in batch:
                        sb_message = ServiceBusMessage(
                            body=msg.model_dump_json(),
                            content_type="application/json"
                        )
                        sb_messages.append(sb_message)

                    # Send batch
                    try:
                        await sender.send_messages(sb_messages)
                        messages_sent += len(sb_messages)
                    except Exception as e:
                        errors.append(f"Batch {batch_count}: {e}")

        elapsed_ms = (time.time() - start_time) * 1000

        return BatchResult(
            success=len(errors) == 0,
            messages_sent=messages_sent,
            batch_count=batch_count,
            elapsed_ms=elapsed_ms,
            errors=errors if errors else None
        )

    def complete_message(self, receiver: ServiceBusReceiver, message: Any) -> bool:
        """
        Complete a message (mark as processed).

        Args:
            receiver: The receiver that received the message
            message: The message object from receive_messages

        Returns:
            True if completed successfully
        """
        try:
            receiver.complete_message(message)
            logger.debug(f"✅ Message completed: {message.message_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to complete message: {e}")
            return False

    def abandon_message(self, receiver: ServiceBusReceiver, message: Any) -> bool:
        """
        Abandon a message (return to queue for retry).

        Args:
            receiver: The receiver that received the message
            message: The message object

        Returns:
            True if abandoned successfully
        """
        try:
            receiver.abandon_message(message)
            logger.debug(f"🔄 Message abandoned: {message.message_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to abandon message: {e}")
            return False

    def __del__(self):
        """Clean up resources on deletion."""
        if hasattr(self, '_initialized'):
            # Close all senders (with logging instead of silent swallow)
            for queue_name, sender in self._senders.items():
                try:
                    sender.close()
                    logger.debug(f"✅ Closed sender for queue: {queue_name}")
                except Exception as close_err:
                    # Log but don't raise - we're in __del__
                    logger.warning(f"⚠️ Error closing sender for {queue_name}: {close_err}")

            # NOTE: Receivers are NOT cached (created fresh each time)
            # So there's no self._receivers to close

            # Close clients
            if hasattr(self, 'client'):
                try:
                    self.client.close()
                    logger.debug("✅ Closed ServiceBusClient")
                except Exception as client_err:
                    logger.warning(f"⚠️ Error closing ServiceBusClient: {client_err}")

            if hasattr(self, 'async_client') and self.async_client:
                # Note: Async cleanup requires event loop
                logger.debug("⚠️ AsyncServiceBusClient cleanup skipped (requires event loop)")


# Factory function for dependency injection
def get_service_bus_repository() -> ServiceBusRepository:
    """
    Get ServiceBusRepository singleton instance.

    Returns:
        ServiceBusRepository singleton instance
    """
    return ServiceBusRepository.instance()