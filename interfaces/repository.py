# ============================================================================
# CLAUDE CONTEXT - INTERFACE
# ============================================================================
# PURPOSE: Abstract interface for queue operations to ensure consistent implementation
# EXPORTS: IQueueRepository - Abstract base class for queue repositories
# INTERFACES: ABC (Abstract Base Class) defining queue operation contracts
# PYDANTIC_MODELS: Uses BaseModel for message type hints
# DEPENDENCIES: abc, typing, pydantic
# SOURCE: Interface definition for concrete implementations
# SCOPE: Queue operations abstraction layer
# VALIDATION: Type hints and abstract method enforcement
# PATTERNS: Interface segregation, dependency inversion
# ENTRY_POINTS: Inherited by concrete repository implementations
# INDEX: IQueueRepository:40
# ============================================================================

"""
Queue Repository Interface

Defines the contract for all queue operations in the system.
This interface ensures consistent authentication, error handling,
and monitoring across all queue implementations.

All queue operations should go through implementations of this interface
to maintain clean separation between business logic and infrastructure.

Author: Azure Geospatial ETL Team
Version: 1.0.0
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from pydantic import BaseModel


class IQueueRepository(ABC):
    """
    Interface for queue operations.

    All queue operations go through this interface, ensuring
    consistent authentication, error handling, and monitoring.

    Implementations should handle:
    - Authentication and credential management
    - Connection pooling and reuse
    - Retry logic and error handling
    - Message encoding/decoding
    - Logging and monitoring
    """

    @abstractmethod
    def send_message(self, queue_name: str, message: BaseModel) -> str:
        """
        Send a message to specified queue.

        Args:
            queue_name: Target queue name
            message: Pydantic model to send

        Returns:
            Message ID

        Raises:
            RuntimeError: If send fails after retries
        """
        pass

    @abstractmethod
    def receive_messages(
        self,
        queue_name: str,
        max_messages: int = 1,
        visibility_timeout: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Receive messages from queue.

        Args:
            queue_name: Queue to receive from
            max_messages: Maximum messages to receive (1-32)
            visibility_timeout: How long to hide messages (seconds)

        Returns:
            List of message dictionaries with content and metadata
        """
        pass

    @abstractmethod
    def delete_message(self, queue_name: str, message_id: str, pop_receipt: str) -> bool:
        """
        Delete a message from queue.

        Args:
            queue_name: Queue containing the message
            message_id: Message ID
            pop_receipt: Pop receipt from receive operation

        Returns:
            True if deleted successfully
        """
        pass

    @abstractmethod
    def peek_messages(self, queue_name: str, max_messages: int = 1) -> List[Dict[str, Any]]:
        """
        Peek at messages without removing them.

        Args:
            queue_name: Queue to peek at
            max_messages: Maximum messages to peek (1-32)

        Returns:
            List of message dictionaries
        """
        pass

    @abstractmethod
    def get_queue_length(self, queue_name: str) -> int:
        """
        Get approximate number of messages in queue.

        Args:
            queue_name: Queue to check

        Returns:
            Approximate message count
        """
        pass

    @abstractmethod
    def clear_queue(self, queue_name: str) -> bool:
        """
        Clear all messages from queue.

        WARNING: This deletes ALL messages. Use with extreme caution.

        Args:
            queue_name: Queue to clear

        Returns:
            True if cleared successfully
        """
        pass